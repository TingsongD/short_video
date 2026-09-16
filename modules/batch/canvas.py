"""Official Canvas only: drafts, exact quotes, stable submissions and recovery."""
import math
import time
import uuid
from pathlib import Path

from modules.assets.canvas_cli import CanvasCLI, CanvasError
from modules.assets.canvas import new_node_id
from .local import verify_media
from .state import Pause, digest, now, write

CAPTURE = ("A photograph captured as a single frame from a video actually shot on an iPhone, "
           "with the texture of real iPhone footage. The image looks real, without an oily, "
           "overprocessed finish. The background is clearly visible, with no depth-of-field blur. "
           "Skin texture is natural and fine, and the lighting is natural. The image is coherent "
           "and free of visual artifacts.")


def ids():
    return {"node_id": new_node_id(), "update_id": str(uuid.uuid4()),
            "submit_id": str(uuid.uuid4()), "resource_id": str(uuid.uuid4()), "stage": "planned"}


def bind(node):
    return "{{node:" + node + "}}"


class Canvas:
    def __init__(self, batch, number, local, cli=None):
        self.batch, self.number, self.local = batch, number, local
        self.v, self.folder = batch.video(number), batch.directory(number)
        self.cli = cli or CanvasCLI()

    def save(self):
        self.batch.save()

    def preflight(self):
        account = self.cli.doctor()
        if not account.get("isVip"):
            raise Pause("The selected membership model requires the intended Jimeng account")
        expected = self.batch.data.setdefault("canvas_account", account["userId"])
        if account["userId"] != expected:
            raise Pause("Jimeng account differs from this batch's original account")
        catalogs = {kind: self.cli.catalog(kind) for kind in ("image", "video")}
        for kind, model, mode, resolution in [("image", "seedream_5.0_pro", "i2i", "2K"),
                                               ("video", "seedance_2.0_fast_vip", "m2v", "720p")]:
            m = next((x for x in catalogs[kind] if x.get("model") == model), None)
            selected = next((x for x in (m or {}).get("modes", []) if x.get("name") == mode), None)
            if not selected:
                raise Pause("Required generation model or reference mode is unavailable")
            flags = {f["flag"]: f for f in selected["flags"]}
            if resolution not in flags["--resolution"]["values"] or "9:16" not in flags["--ratio"]["values"]:
                raise Pause("Required generation resolution or ratio is unsupported")
            if kind == "video" and (flags["--duration"]["min"] > 4 or flags["--duration"]["max"] < 15):
                raise Pause("Video model duration limits changed")
        self.v["preflight"] = {"at": now(), "canvas": account, "catalogs": catalogs}
        self.save()

    def project(self):
        if "project_id" not in self.v:
            self.v.update(project_id=str(uuid.uuid4()), canvas_stage="creating")
            self.save()
            r = self.cli.call("canvas", "create", f"MsDressly haul {self.number:02}: {self.batch.selected(self.number)['theme']}",
                              "--project-id", self.v["project_id"])
            if r.get("project", {}).get("projectId") != self.v["project_id"]:
                raise Pause("Canvas creation identity mismatch")
            self.v.update(canvas_stage="created", web_url=r["project"].get("webUrl"))
            self.save()
        elif self.v.get("canvas_stage") != "created":
            found = self.cli.find_canvas(self.v["project_id"])
            if not found:
                raise Pause("Canvas creation response ambiguous; reconcile the saved project ID")
            self.v.update(canvas_stage="created", web_url=found.get("webUrl"))
            self.save()
        return self.v["project_id"]

    def import_file(self, key, kind, path, source_url=None, existing_resource=None):
        imports = self.v["imports"]
        path = Path(path).resolve()
        if key not in imports:
            imports[key] = {**ids(), "kind": kind, "sha256": digest(path), "path": str(path)}
            if existing_resource:
                imports[key].update(resource_id=existing_resource, stage="uploaded", provenance="borrow_existing_accepted_resource")
            if source_url:
                imports[key]["source_url"] = source_url
            self.save()
        d = imports[key]
        if digest(path) != d["sha256"]:
            raise Pause("Reference changed after import; prepare an intentional revision")
        if d["stage"] == "planned":
            d["stage"] = "uploading"
            self.save()
            source = ["--source-url", d["source_url"]] if d.get("source_url") else ["--file", path]
            result = self.cli.call("resource", "upload", "--project-id", self.project(), *source,
                                   "--type", kind, "--resource-id", d["resource_id"], "--name", key, timeout=180)
            if result.get("resourceId") != d["resource_id"]:
                raise Pause("Reference upload identity mismatch")
            d["stage"] = "uploaded"
            self.save()
        if d["stage"] == "uploaded":
            d["stage"] = "importing"
            self.save()
            self.cli.call("node", "create", kind, "--project-id", self.project(), "--node-id", d["node_id"],
                          "--update-id", d["update_id"], "--submit-id", d["submit_id"], "--title", key,
                          "--resource-id", d["resource_id"], "--import-kind", "external_generated" if existing_resource else "local_upload")
            d["stage"] = "imported"
            self.save()
        if d["stage"] == "importing":
            node = self.cli.node(self.project(), d["node_id"])
            if node:
                d["stage"] = "imported"
                self.save()
        if d["stage"] != "imported":
            raise Pause(f"Reference {key} requires upload recovery using its saved resource ID")
        return d["node_id"]

    def draft(self, key, kind, prompt, refs, duration=None):
        if key not in self.v["jobs"]:
            self.v["jobs"][key] = {**ids(), "kind": kind, "prompt": prompt, "refs": refs,
                    "model": "seedream_5.0_pro" if kind == "image" else "seedance_2.0_fast_vip",
                    "mode": "i2i" if kind == "image" else "m2v", "duration": duration}
            self.save()
        j = self.v["jobs"][key]
        if j["stage"] == "planned":
            j["stage"] = "saving"
            self.save()
            self._save_draft(key, "create")
            j["stage"] = "saved"
            self.save()
        elif j["stage"] == "saving":
            node = self.cli.node(self.project(), j["node_id"])
            if not node:
                raise Pause("Recover draft creation using the saved node ID")
            j["stage"] = "saved"
            self.save()
        return j["node_id"]

    def _save_draft(self, key, action):
        j = self.v["jobs"][key]
        args = ["node", action, j["kind"], "--project-id", self.project(), "--node-id", j["node_id"],
                "--update-id", j["update_id"], "--title", key, "--model", j["model"], "--mode", j["mode"],
                "--resolution", "2K" if j["kind"] == "image" else "720p", "--ratio", "9:16", "--count", 1,
                "--prompt", j["prompt"]]
        if j["kind"] == "video":
            if type(j["duration"]) is not int or not 4 <= j["duration"] <= 15:
                raise Pause("Unsupported generation duration")
            args += ["--duration", j["duration"]]
        for ref in j["refs"]:
            args += ["--ref", "node:" + ref]
        self.cli.call(*args)

    def attach_audio(self, key, node, words):
        j = self.v["jobs"][key]
        if j.get("audio_node") == node and j["stage"] != "editing":
            return
        if j["stage"] not in ("saved", "editing"):
            raise Pause("Cannot revise a submitted generation")
        if j["stage"] != "editing":
            if j.get("quote_audio_node") in j["refs"]:
                j["refs"] = [node if ref == j["quote_audio_node"] else ref for ref in j["refs"]]
            else:
                j["refs"].append(node)
            j["prompt"] += ("\n" + bind(node) + " is the final English voice recording. Follow its EXACT phonemes, "
                "words, pauses and timing with precise natural lip-sync. Use this recording without rewriting or adding speech. "
                "No background music. SCRIPT: " + words)
            j.update(audio_node=node, update_id=str(uuid.uuid4()), stage="editing")
            self.save()
        self._save_draft(key, "edit")  # same update ID is idempotent, no paid run
        j["stage"] = "saved"
        self.save()

    def set_references(self, key, refs, prompt):
        j = self.v["jobs"][key]
        if j["refs"] == refs and j["prompt"] == prompt and j["stage"] != "editing":
            return
        if j["stage"] not in ("saved", "editing"):
            raise Pause("Submitted media references cannot be changed")
        if j["stage"] != "editing":
            j.update(refs=refs, prompt=prompt, update_id=str(uuid.uuid4()), stage="editing")
            self.save()
        self._save_draft(key, "edit")
        j["stage"] = "saved"
        self.save()

    def bind_outfit(self, key, outfit):
        j = self.v["jobs"][key]
        prior = j.get("quote_outfit_node")
        if not prior or j.get("production_outfit_node") == outfit:
            return
        refs = [outfit if n == prior else n for n in j["refs"]]
        self.set_references(key, refs, j["prompt"].replace(bind(prior), bind(outfit)))
        j["production_outfit_node"] = outfit
        self.save()

    def retime(self, key, duration):
        j = self.v["jobs"][key]
        if j["duration"] == duration and j["stage"] != "editing":
            return False
        if j["stage"] not in ("saved", "editing"):
            raise Pause("Cannot change the duration of an already-submitted shot")
        if j["stage"] != "editing":
            j.update(duration=duration, update_id=str(uuid.uuid4()), stage="editing")
            self.save()
        self._save_draft(key, "edit")
        j["stage"] = "saved"
        self.save()
        return True

    def quote_all(self):
        quotes = {}
        for key, j in self.v["jobs"].items():
            if j.get("authorized_credits") is not None:
                quotes[key] = j["authorized_credits"]
            else:
                self.check_draft(key)
                q = self.cli.quote(self.project(), [j["node_id"]])
                j.update(quoted_credits=q["totalMaxCredits"], quote=q, quoted_at=now())
                quotes[key] = q["totalMaxCredits"]
                self.save()
        write(self.folder / "quotes.json", {"unit": "Jimeng credits", "items": quotes,
              "total": sum(quotes.values()), "correction_reserve": 200, "quoted_at": now()})
        self.batch.reserve_video(self.number, quotes)
        return quotes

    def check_draft(self, key):
        j = self.v["jobs"][key]
        node = self.cli.node(self.project(), j["node_id"])
        generation = node.get("generation", {})
        expected = {"model": j["model"], "mode": j["mode"], "ratio": "9:16", "outputCount": 1,
                    "resolution": "2K" if j["kind"] == "image" else "720p"}
        if j["kind"] == "video":
            expected["durationSeconds"] = j["duration"]
        references = generation.get("references", [])
        if node.get("type") != j["kind"] or any(generation.get(k) != value for k, value in expected.items()):
            raise Pause("Canvas generation settings changed after preparation")
        if [(r.get("kind"), r.get("id")) for r in references] != [("node", n) for n in j["refs"]]:
            raise Pause("Canvas reference identities or order changed after preparation")
        actual = generation.get("prompt")
        if generation.get("promptParts"):
            parts = []
            for part in generation["promptParts"]:
                if part.get("kind") == "text":
                    parts.append(part["text"])
                elif part.get("kind") == "reference":
                    parts.append(bind(references[part["referenceIndex"]]["id"]))
                else:
                    raise Pause("Unsupported Canvas prompt component")
            actual = "".join(parts)
        if actual != j["prompt"]:
            raise Pause("Canvas prompt changed; an intentional revision is required")
        return node

    def finish(self, key):
        j = self.v["jobs"][key]
        if j["stage"] == "downloaded":
            path = self.folder / j["file"]
            if path.exists() and digest(path) == j["sha256"]:
                return path
            j["stage"] = "succeeded"  # re-download an existing paid resource
            self.save()
        if j["stage"] == "saved":
            self.check_draft(key)
            q = self.cli.quote(self.project(), [j["node_id"]])
            self.batch.claim_visual(self.number, key, q["totalMaxCredits"])
            try:
                result = self.cli.submit(self.project(), j["node_id"], j["submit_id"], q["totalMaxCredits"])
                items = result.get("items", [])
                j["acceptance"] = [{k: x[k] for k in ("nodeId", "submitId", "state", "result", "resourceId") if k in x} for x in items]
                if len(items) != 1 or items[0].get("nodeId") != j["node_id"] or items[0].get("submitId") != j["submit_id"]:
                    j["stage"] = "unknown"
                    self.save()
                    raise Pause("Submission response identity uncertain; recover the existing submission ID")
                observed = str(items[0].get("state", "unknown")).lower()
                j["stage"] = observed if observed in ("accepted", "rejected") else "unknown"
            except CanvasError:
                j["stage"] = "unknown"
                self.save()
                raise
            self.save()
        if j["stage"] in ("submitting", "submitted", "accepted", "pending", "running", "unknown"):
            # ALL restarts use read-only status/wait on the SAME saved submission.
            while True:
                op = self.cli.call("operation", "wait", j["submit_id"], "--project-id", self.project(),
                                   "--timeout", "45s", "--interval", "10s", timeout=55, incomplete=True)
                if not op:
                    op = self.cli.call("operation", "status", j["submit_id"], "--project-id", self.project(), incomplete=True)
                if op.get("operationRef") != j["submit_id"]:
                    j["stage"] = "unknown"
                    self.save()
                    raise Pause("Operation response identity uncertain; recover the saved submission")
                j["observed_state"] = op.get("state")
                self.save()
                if op.get("state") in ("failed", "cancelled", "rejected"):
                    j["stage"] = op["state"]
                    self.save()
                    raise Pause(f"{key} failed; a correction requires a recorded defect and new quote")
                if op.get("state") == "succeeded":
                    resources = [r["resourceId"] for r in op.get("resources", []) if r.get("state") == "succeeded"]
                    if len(resources) != 1:
                        raise Pause("Generation returned an unexpected result count")
                    node = self.cli.node(self.project(), j["node_id"])
                    if not any(r.get("resourceId") == resources[0] and r.get("submitId") == j["submit_id"]
                               and r.get("type") == j["kind"] for r in node.get("resources", [])):
                        raise Pause("Downloaded output provenance does not match the saved node and submission")
                    j.update(stage="succeeded", output_resource_id=resources[0])
                    self.save()
                    break
                print(f"{key}: {op.get('state', 'unknown')}", flush=True)
                time.sleep(2)
        if j["stage"] != "succeeded":
            raise Pause(f"{key} needs recovery: {j['stage']}")
        ext = ".jpg" if j["kind"] == "image" else ".mp4"
        path = self.folder / "assets" / (key + ".jimeng" + ext)
        path.parent.mkdir(exist_ok=True)
        # A crashed/partial download is free to retry; never re-run generation.
        temp = path.with_name(path.stem + ".download" + ext)
        if temp.exists():
            temp.unlink()
        self.cli.call("resource", "download", j["output_resource_id"], "--project-id", self.project(),
                      "--output", temp, timeout=240)
        verification = verify_media(self.local, temp, j["kind"], j.get("timeline_seconds", 0))
        temp.replace(path)
        j.update(stage="downloaded", file=str(path.relative_to(self.folder)), **verification)
        self.save()
        return path


def image_prompt(avatar, product, description, styling):
    return (CAPTURE + "\n\nPreserve the exact fictional adult presenter in " + bind(avatar) +
        ": her face, warm medium-brown skin, curly bob, broad shoulders, realistic proportions and small gold hoops. "
        "Change her clothes to the exact product in " + bind(product) + ": " + description + ". " + styling +
        "\n\nFull body head to shoes, hands relaxed clear of the garment, centered facing the fixed camera, "
        "natural speaking-ready smile. Preserve garment color, pattern scale, seams, closures, hem and drape from the product photograph. "
        "\n\nKeep the reference home: gray walls and white molding, black paneled door at right, light wood cabinet, "
        "green plant and cream rug. Preserve framing and natural light. No text, labels, logos or watermarks.")


def video_prompt(outfit, product, action):
    return ("Create a realistic vertical phone-shot fashion try-on video. " + bind(outfit) +
        " is the visible speaker and scene reference. Preserve her identity, face, outfit, setting, lighting, lens feel, "
        "and broad composition. " + bind(product) + " supplies the exact featured garment. "
        "Keep this outfit unchanged from first to last frame. Hold a steady fixed camera, same full-body composition, "
        "natural responsive conversation and compact gestures. " + action +
        " Keep face, hands, skin texture and motion coherent and photoreal. No subtitles, captions, labels, logos, "
        "floating words, outfit changes, duplicate people or unrelated objects.")
