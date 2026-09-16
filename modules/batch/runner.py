"""One video from selection to delivery. Operator reviews are durable agent checkpoints."""
import hashlib
import json
import math
import shutil
import urllib.request
from pathlib import Path

from modules.assets.canvas_cli import CanvasError
from .audio import Audio
from .canvas import Canvas, image_prompt, video_prompt
from .local import Drive, Local
from .picture import selected_picture
from .render import HYPIT, Render
from .state import Pause, ReviewReady, digest, now, read, write

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "data/production/next-15-video-plan-20260915"
PREVIOUS = ROOT / "data/production/v-product-variation-Db9SrsBsIUg/hypit-full-length-01"


def validate_brief(brief, selection):
    products, takes = brief["products"], brief["takes"]
    if len(products) != 10 or [p["product_id"] for p in products] != [p["product_id"] for p in selection["products"]]:
        raise Pause("The ten selected products and their order must be preserved")
    if len({t["id"] for t in takes}) != len(takes) or not takes or takes[0]["start_frame"] != 0 or takes[-1]["end_frame"] != 5091:
        raise Pause("Takes must uniquely cover the complete 169.7-second video")
    cursor = 0
    for take in takes:
        count = take["end_frame"] - take["start_frame"]
        if take["start_frame"] != cursor or not 120 <= count <= 450 or take["slot"] not in range(1, 11):
            raise Pause("Invalid shot order, gap, overlap or unsupported duration")
        if not take["text"].strip() or any(x in take["text"] for x in ("&#", "<", ">", "[", "]")):
            raise Pause("Narration must contain clean spoken copy")
        cursor = take["end_frame"]
    if set(t["slot"] for t in takes) != set(range(1, 11)):
        raise Pause("Every selected product needs footage")
    if sum(len(t["text"]) for t in takes) > 4000:
        raise Pause("Rewrite narration within the video's 4,000-credit ceiling before synthesis")
    if Path(brief["delivery_name"]).name != brief["delivery_name"] or not brief["delivery_name"].endswith(".mp4"):
        raise Pause("Delivery filename must be a plain descriptive MP4 filename")


def check_review(v, key, fingerprint):
    r = v.get("reviews", {}).get(key, {})
    return r.get("status") == "passed" and r.get("fingerprint") == fingerprint


def review_fingerprint(v, folder, key):
    if key == "narration":
        return digest(folder / "audio/narration.wav")
    if key == "final":
        return digest(v["final_path"])
    if key == "products":
        products = [{k: value for k, value in p.items() if k != "reference_path"}
                    for p in read(folder / "brief.json")["products"]]
        return hashlib.sha256(json.dumps(products, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if key not in v["jobs"] or v["jobs"][key]["stage"] != "downloaded":
        raise Pause("The requested review has no completed artifact")
    if v["jobs"][key]["kind"] == "video":
        return digest(selected_picture(v, folder, key))
    return digest(folder / v["jobs"][key]["file"])


def record_review(batch, number, key, verdict, notes):
    v, folder = batch.video(number), batch.directory(number)
    if verdict not in ("passed", "failed") or len(notes.strip()) < 12:
        raise Pause("Record an inspection verdict and concrete evidence")
    if number != batch.active_number():
        raise Pause("Only the active video's artifacts can be reviewed")
    fingerprint = review_fingerprint(v, folder, key)
    v.setdefault("reviews", {})[key] = {"status": verdict, "notes": notes, "at": now(), "fingerprint": fingerprint}
    if key == "final":
        v["qc"] = {"status": verdict, "sha256": fingerprint, "notes": notes, "at": now()}
    batch.save()


class Runner:
    def __init__(self, batch, number):
        self.batch, self.number = batch, number
        self.v, self.folder = batch.video(number), batch.directory(number)
        self.local = Local(self.folder)
        self.canvas = Canvas(batch, number, self.local)

    def products(self, brief):
        refs = self.folder / "references"
        refs.mkdir(exist_ok=True)
        for product, selected in zip(brief["products"], self.batch.selected(self.number)["products"]):
            path = refs / (product["product_id"] + ".jpg")
            request = urllib.request.Request(selected["onlineStoreUrl"] + ".js", headers={"User-Agent": "MsDressly production stock check"})
            with urllib.request.urlopen(request, timeout=45) as response:
                live = json.load(response)
            available = [v for v in live["variants"] if v["available"]]
            variant = next((v for v in available if str(v["id"]) == str(product["variant_id"])), None)
            if not variant:
                raise Pause(f"Product {product['slot']} selected variant is unavailable; review before generation")
            images = [x if isinstance(x, str) else x["src"] for x in live["images"]]
            source = product["image_url"]
            if source.split("?")[0].removeprefix("https:") not in [x.split("?")[0].removeprefix("https:") for x in images]:
                raise Pause("Selected reference image no longer belongs to this Shopify product")
            if not path.exists():
                url = "https:" + source if source.startswith("//") else source
                with urllib.request.urlopen(url, timeout=60) as response:
                    data = response.read(30 * 1024 * 1024)
                if len(data) < 1000:
                    raise Pause("Product image download incomplete")
                path.write_bytes(data)
            product["reference_path"] = str(path)
            write(refs / (product["product_id"] + "-stock.json"), {"at": now(), "product_id": product["product_id"],
                  "variant_id": variant["id"], "variant_title": variant["title"], "available": True,
                  "price_cents": variant["price"], "image_sha256": digest(path), "url": selected["onlineStoreUrl"]})

    def prepare(self, brief):
        health = self.local.health()
        if health["memory_free_percent"] is None or health["memory_free_percent"] < 15 or health["disk_free_bytes"] < 25 * 1024**3:
            raise Pause("Insufficient free memory or disk space before generation")
        self.v["resource_preflight"] = {"at": now(), **health}
        self.batch.save()
        self.canvas.preflight()
        self.canvas.project()
        self.products(brief)
        assets = self.folder / "assets"
        assets.mkdir(exist_ok=True)
        prior_avatar = read(PREVIOUS / "canvas-state.json")["jobs"]["look-tank-blue"]
        avatar = self.canvas.import_file("accepted-presenter-borrow", "image", PREVIOUS / "assets/presenter-tank-blue.jpg",
                    existing_resource=prior_avatar.get("output_resource_id") or prior_avatar["selected_resource_id"])
        prior_voice = read(PREVIOUS / "canvas-state.json")["imports"]["clip-01-Jessica-voice"]
        quote_voice = self.canvas.import_file("quote-voice-reference", "audio", PREVIOUS / "audio/clip-01-reference.wav",
                                              existing_resource=prior_voice["resource_id"])
        for product in brief["products"]:
            key = f"product-{product['slot']:02}"
            url = product["image_url"]
            node = self.canvas.import_file(key, "image", product["reference_path"], source_url="https:" + url if url.startswith("//") else url)
            look = f"look-{product['slot']:02}"
            outfit = self.canvas.draft(look, "image", image_prompt(avatar, node, product["description"], product["styling"]), [avatar, node])
            for take in [t for t in brief["takes"] if t["slot"] == product["slot"]]:
                prompt = video_prompt(avatar, node, take["action"])
                refs = [avatar, node, quote_voice]
                self.canvas.draft(take["id"], "video", prompt, refs, math.ceil((take["end_frame"] - take["start_frame"]) / 30))
                if not self.v["reservation"]:
                    self.canvas.set_references(take["id"], refs, prompt)
                    self.v["jobs"][take["id"]].update(quote_audio_node=quote_voice, quote_outfit_node=avatar,
                       planned_outfit_node=outfit, quote_basis="same model/duration/resolution/count and two-image/one-audio references; swap accepted performance before generation")
                self.v["jobs"][take["id"]]["timeline_seconds"] = (take["end_frame"] - take["start_frame"]) / 30
        self.batch.save()
        if not self.v["reservation"]:
            self.v["state"] = "prepared"
            self.batch.save()
            self.canvas.quote_all()

    def require_review(self, key):
        fingerprint = review_fingerprint(self.v, self.folder, key)
        if not check_review(self.v, key, fingerprint):
            self.v["review_required"] = key
            self.batch.save()
            if self.v.get("reviews", {}).get(key, {}).get("status") == "failed":
                raise Pause(f"{key} failed review; inspect the required correction")
            raise ReviewReady(f"Inspect {key} now, record its review, and continue this agent turn")
        self.v.pop("review_required", None)
        self.batch.save()

    def reviewed(self, key):
        if key not in self.v.get("reviews", {}):
            return False
        return check_review(self.v, key, review_fingerprint(self.v, self.folder, key))

    def run(self):
        if self.number != self.batch.active_number():
            raise Pause("Only one active video is allowed; finish the preceding video's delivery and cleanup")
        try:
            self.batch.data.update(status="running", pause_reason=None)
            self.batch.save()
            self._run()
        except ReviewReady as error:
            self.batch.data.update(status="review_ready", pause_reason=str(error))
            self.batch.save()
            raise
        except (Pause, CanvasError) as error:
            self.batch.data.update(status="paused", pause_reason=str(error), paused_at=now())
            self.batch.save()
            raise
        finally:
            # Also happens for upload failure, review checkpoints and generation errors.
            self.v["cleanup"] = self.local.cleanup(HYPIT)
            self.batch.save()
        if self.v.get("delivery", {}).get("state") == "verified":
            self.batch.complete(self.number)

    def _run(self):
        brief_path = self.folder / "brief.json"
        if not brief_path.exists():
            raise Pause(f"Write the original copy and reference directions in {brief_path}")
        brief = read(brief_path)
        validate_brief(brief, self.batch.selected(self.number))
        fingerprint = digest(brief_path)
        if self.v.get("brief_sha256") and self.v["brief_sha256"] != fingerprint:
            raise Pause("Production brief changed after preparation; reconcile accepted work before spending")
        self.v["brief_sha256"] = fingerprint
        self.batch.save()
        self.require_review("products")
        if self.v.get("delivery", {}).get("state") == "verified":
            Drive(self.local, self.batch.plan["delivery_folder_id"]).upload(self.v["final_path"], self.folder / "upload-receipt.json")
            return
        if self.v.get("final_path"):
            self.require_review("final")
        else:
            if self.v.get("prepared_brief_sha256") != fingerprint:
                self.prepare(brief)
            else:
                self.canvas.preflight()  # A cached draft never substitutes for current account verification.
            audio = Audio(self.batch, self.number, self.local)
            narration = self.folder / "audio/narration.wav"
            audio_receipt = self.folder / "audio/audio-verification.json"
            if (not narration.exists() or not audio_receipt.exists()
                    or digest(narration) != read(audio_receipt)["sha256"]):
                audio.finish(brief, PREVIOUS / "audio/music-bed.wav")
            if any(self.v["jobs"][t["id"]]["duration"] != math.ceil((t["end_frame"] - t["start_frame"]) / 30)
                   for t in brief["takes"]):
                self.v["timing_quote_required"] = True
                self.batch.save()
            for take in brief["takes"]:
                self.canvas.retime(take["id"], math.ceil((take["end_frame"] - take["start_frame"]) / 30))
                self.v["jobs"][take["id"]]["timeline_seconds"] = (take["end_frame"] - take["start_frame"]) / 30
            if self.v.get("timing_quote_required"):
                self.canvas.quote_all()
                self.v["timing_quote_required"] = False
                self.batch.save()
            self.v["prepared_brief_sha256"] = digest(brief_path)
            self.batch.save()
            self.require_review("narration")
            from .scheduler import Scheduler
            Scheduler(self, brief).finish()
            self.v["state"] = "footage_ready"
            self.batch.save()
            Render(self.batch, self.number, self.local, PREVIOUS).finish(brief)
            self.require_review("final")
        self.v["delivery"] = Drive(self.local, self.batch.plan["delivery_folder_id"]).upload(
            self.v["final_path"], self.folder / "upload-receipt.json")
        self.batch.save()


def repair(batch, number, key, prompt):
    v = batch.video(number)
    if number != batch.active_number() or v.get("reviews", {}).get(key, {}).get("status") != "failed":
        raise Pause("A replacement requires an inspected, recorded defect in the active video")
    original = v["jobs"][key]
    if original["stage"] != "downloaded":
        raise Pause("A visual replacement requires the completed, inspected source artifact")
    if original.get("replacement_for") or any(x.get("replacement_for") == key for x in v["jobs"].values()):
        raise Pause("At most one replacement per defective shot")
    corrections = [j for j in v["jobs"].values() if j.get("replacement_for")]
    if sum(j["kind"] == original["kind"] for j in corrections) >= 2:
        raise Pause("At most two video and two image corrections per video")
    local = Local(batch.directory(number))
    canvas = Canvas(batch, number, local)
    if original["kind"] == "image" and any(original["node_id"] in t.get("refs", []) and t["stage"] != "saved"
                                              for t in v["jobs"].values()):
        raise Pause("Dependent footage already submitted; reconcile explicitly")
    new_key = key + "-repair-01"
    canvas.draft(new_key, original["kind"], prompt, original["refs"], original.get("duration"))
    job = v["jobs"][new_key]
    quote = canvas.cli.quote(canvas.project(), [job["node_id"]])
    amount = quote["totalMaxCredits"]
    correction_hold = sum(j.get("quoted_credits", 0) for j in corrections)
    if amount + correction_hold > batch.plan["repair_allowance_credits_per_video"]:
        raise Pause("Correction allowance exhausted")
    job.update(replacement_for=key, quoted_credits=amount, quote=quote,
               timeline_seconds=original.get("timeline_seconds", 0), audio_node=original.get("audio_node"))
    v.setdefault("selected_jobs", {})[key] = new_key
    # Image replacement feeds all still-unsubmitted takes through a fresh draft edit.
    if original["kind"] == "image":
        for take_key, take in v["jobs"].items():
            if original["node_id"] in take.get("refs", []):
                if take["stage"] != "saved":
                    raise Pause("Dependent footage already submitted; reconcile explicitly")
                take["refs"] = [job["node_id"] if n == original["node_id"] else n for n in take["refs"]]
                take["prompt"] = take["prompt"].replace(original["node_id"], job["node_id"])
                import uuid
                take.update(update_id=str(uuid.uuid4()), stage="editing")
                batch.save()
                canvas._save_draft(take_key, "edit")
                take["stage"] = "saved"
    batch.save()
