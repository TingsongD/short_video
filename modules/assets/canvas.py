"""Recoverable shot-list -> Canvas -> validated local media workflow.

Prepare only saves drafts and quotes. Generate requires an explicit integer
credit ceiling. Resume/status NEVER call create, confirm, or run.
"""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

from modules.common.config import DATA_DIR
from .canvas_cli import CanvasCLI, CanvasError
from .canvas_models import choose_model, generation_parameters
from .canvas_state import atomic_json, generation_lock, read_state
from .intake import scan_folder, validate_file
from .manifest import build_manifest, write_manifest
from .queue import render_cards, validate_shots, validate_video_id

STATE_NAME = "jimeng_jobs.json"
ACTIVE = {"submitting", "accepted", "pending", "running", "unknown"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _node_params(params):
    return {"mode": params["mode"], "model": params["model"], "prompt": params["prompt"],
            "ratio": params["ratio"], "resolution": params["resolution"],
            "outputCount": int(params["count"]),
            **({"durationSeconds": float(params["duration"])} if "duration" in params else {})}


class CanvasAssets:
    def __init__(self, cli=None, base=None, settings=None):
        self.cli = cli or CanvasCLI()
        self.base = Path(base or DATA_DIR / "production")
        self.settings = settings or {}

    def path(self, video_id):
        validate_video_id(video_id)
        return self.base / video_id / "assets" / STATE_NAME

    def _save(self, job):
        atomic_json(self.path(job["video_id"]), job)

    def _identity(self, job):
        actual = self.cli.doctor()
        for key in ("profile", "region", "environment", "userId"):
            if actual[key] != job["account"][key]:
                raise CanvasError("job_account_mismatch", "use the original account and region")
        return actual

    def _check_node(self, job, item):
        node = self.cli.node(job["project_id"], item["node_id"])
        generation = node.get("generation", {})
        expected = _node_params(item["parameters"])
        if node.get("type") != item["kind"] or any(generation.get(k) != v for k, v in expected.items()):
            raise CanvasError("draft_changed", "review the edited shot; prepare a new video_id")
        if generation.get("references"):
            raise CanvasError("draft_references_changed")
        return node

    def _quote(self, job, items):
        if not items:
            return {"items": [], "totalMaxCredits": 0}
        for item in items:
            self._check_node(job, item)
        return self.cli.quote(job["project_id"], [i["node_id"] for i in items])

    def prepare(self, shot_list, only_shots=None):
        validate_shots(shot_list)
        selected = sorted(set(only_shots if only_shots is not None else
                              [s["idx"] for s in shot_list["shots"]]))
        if not selected or any(i not in range(len(shot_list["shots"])) for i in selected):
            raise ValueError("selected shot is not in the shot list")
        digest = fingerprint({"shot_list": shot_list, "settings": self.settings,
                              "selected_shots": selected})
        with generation_lock(self.base):
            path = self.path(shot_list["video_id"])
            if path.exists():
                job = read_state(path)
                if job["fingerprint"] != digest:
                    raise CanvasError("generation_changed", "use a new video_id for an explicit new generation")
                self._identity(job)
            else:
                account = self.cli.doctor()
                plans = []
                models = {}
                # Validate every selected shot before creating any remote object.
                for s in shot_list["shots"]:
                    if s["idx"] not in selected:
                        continue
                    kind = s["asset_type"]
                    if kind not in models:
                        models[kind] = choose_model(self.cli.catalog(kind), kind,
                                                   self.settings.get(f"{kind}_model"))
                    params = generation_parameters(
                        s, models[kind], self.settings.get(f"{kind}_resolution",
                                                          "720P" if kind == "video" else "2K"))
                    plans.append({"idx": s["idx"], "kind": kind, "duration_s": s["duration_s"],
                                  "node_id": "node_" + uuid4().hex, "update_id": str(uuid4()),
                                  "submit_id": str(uuid4()), "parameters": params,
                                  "draft_state": "new", "state": "prepared"})
                job = {"version": 1, "video_id": shot_list["video_id"], "fingerprint": digest,
                       "shot_list_hash": fingerprint(shot_list), "account": account,
                       "project_id": str(uuid4()), "canvas_state": "new", "shots": plans,
                       "credit_unit": "jimeng_credits", "approved_ceiling": None}
                render_cards(shot_list, base=self.base)
                self._save(job)
            project_id = job["project_id"]
            if job["canvas_state"] == "creating":
                project = self.cli.find_canvas(project_id)
                if project is None:
                    raise CanvasError("canvas_creation_uncertain", "inspect canvas history; do not create again")
                job["web_url"] = project["webUrl"]
                job["canvas_state"] = "ready"
                self._save(job)
            if job["canvas_state"] == "new":
                job["canvas_state"] = "creating"
                self._save(job)
                data = self.cli.call("canvas", "create", "Short Form - " + job["video_id"],
                                     "--project-id", project_id)
                project = data.get("project", {})
                if project.get("projectId") != project_id or not project.get("webUrl"):
                    raise CanvasError("canvas_creation_uncertain")
                job["web_url"] = project["webUrl"]
                job["canvas_state"] = "ready"
                self._save(job)
            for item in job["shots"]:
                if item["draft_state"] == "saving":
                    # A lost save response is resolved by a read, never a new node.
                    self._check_node(job, item)
                    item["draft_state"] = "saved"
                    self._save(job)
                if item["draft_state"] == "new":
                    args = ["node", "create", item["kind"], "--project-id", project_id,
                            "--node-id", item["node_id"], "--update-id", item["update_id"],
                            "--title", f"Shot {item['idx']:02d}"]
                    for key, value in item["parameters"].items():
                        args += [f"--{key}", value]
                    item["draft_state"] = "saving"
                    self._save(job)
                    self.cli.call(*args)  # intentionally no --run
                    self._check_node(job, item)
                    item["draft_state"] = "saved"
                    self._save(job)
            self._reuse_local(job)
            fresh = [i for i in job["shots"] if i["state"] == "prepared"]
            job["quote"] = self._quote(job, fresh)
            self._save(job)
            return self.summary(job)

    def _shot_list(self, job):
        doc = json.loads((self.path(job["video_id"]).parent / "_shot_list.json").read_text())
        if fingerprint(doc) != job["shot_list_hash"]:
            raise CanvasError("shot_list_changed", "restore original shot list or use a new video_id")
        return validate_shots(doc)

    def _reuse_local(self, job):
        doc = self._shot_list(job)
        folder = self.path(job["video_id"]).parent
        found = scan_folder(folder, {s["idx"]: s["asset_type"] for s in doc["shots"]},
                            {s["idx"]: s["duration_s"] for s in doc["shots"]})
        for item in job["shots"]:
            if item["state"] in {"prepared", "local"}:
                entry = found.get(item["idx"], {})
                if entry.get("ok"):
                    item["state"], item["file"] = "local", entry["file"]
                elif item["state"] == "local":
                    item["state"] = "prepared"
                    item.pop("file", None)

    def _block_other_active(self, job):
        for path in self.base.glob(f"*/assets/{STATE_NAME}"):
            other = read_state(path)
            if any(i["state"] in ACTIVE for i in other["shots"]):
                raise CanvasError("generation_already_active",
                                  f"resume {other['video_id']} before submitting more shots")

    def generate(self, video_id, ceiling, wait_seconds=45):
        if type(ceiling) is not int or ceiling < 0:
            raise ValueError("credit ceiling must be a nonnegative integer")
        with generation_lock(self.base):
            job = read_state(self.path(video_id))
            self._identity(job)
            self._shot_list(job)
            self._reuse_local(job)
            self._block_other_active(job)
            if any(i["state"] in {"failed", "rejected", "invalid"} for i in job["shots"]):
                raise CanvasError("shot_needs_review", "use manual intake or an explicit new video_id")
            fresh = [i for i in job["shots"] if i["state"] == "prepared"]
            quote = self._quote(job, fresh)
            reserved = sum(i.get("authorized_credit_ceiling", 0) for i in job["shots"])
            if reserved + quote["totalMaxCredits"] > ceiling:
                raise CanvasError("credit_ceiling_exceeded", "review the new quote and remaining allowance")
            if job["approved_ceiling"] is not None and ceiling != job["approved_ceiling"]:
                raise CanvasError("approval_changed", "retain the original batch ceiling")
            job["approved_ceiling"] = ceiling
            job["quote"] = quote
            quoted = {i["nodeId"]: i["maxCredits"] for i in quote["items"]}
            self._save(job)
            for item in fresh:
                # Quote this shot again; both local accounting and server token
                # cap it at the amount originally allocated to this shot.
                current = self._quote(job, [item])["totalMaxCredits"]
                allocation = quoted[item["node_id"]]
                if current > allocation:
                    raise CanvasError("shot_price_increased", "review an updated quote")
                item["authorized_credit_ceiling"] = allocation
                item["state"] = "submitting"
                self._save(job)
                try:
                    data = self.cli.submit(job["project_id"], item["node_id"],
                                           item["submit_id"], allocation)
                except CanvasError:
                    item["state"] = "unknown"
                    self._save(job)
                    raise
                results = data.get("items", [])
                if (len(results) != 1 or results[0].get("nodeId") != item["node_id"]
                        or results[0].get("submitId") != item["submit_id"]):
                    item["state"] = "unknown"
                    self._save(job)
                    raise CanvasError("submission_identity_uncertain", "resume")
                result = results[0]
                state = str(result.get("state", "unknown")).lower()
                item["state"] = state if state in {"accepted", "rejected", "unknown"} else "unknown"
                self._save(job)
                if item["state"] != "accepted":
                    break
                self._observe(job, item, wait_seconds, download=True)
                self._save(job)
                if item["state"] != "downloaded":
                    break
            self._manifest(job)
            return self.summary(job)

    def _observe(self, job, item, wait_seconds=0, download=False):
        if item["state"] in {"prepared", "local", "rejected"}:
            return
        if item["state"] == "downloaded":
            folder = self.path(job["video_id"]).parent
            path = folder / item["file"]
            ok, _ = validate_file(path, item["kind"], item["duration_s"])
            if ok and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256"):
                return
            item["state"] = "succeeded"  # re-download same resource, never regenerate
        command = "wait" if wait_seconds else "status"
        args = ["operation", command, item["submit_id"], "--project-id", job["project_id"]]
        if wait_seconds:
            args += ["--timeout", f"{wait_seconds}s", "--interval", "5s"]
        data = self.cli.call(*args, timeout=wait_seconds + 30, incomplete=True)
        if data.get("operationRef") != item["submit_id"]:
            item["state"] = "unknown"
            return
        state = str(data.get("state", "unknown")).lower()
        item["state"] = state if state in {"pending", "running", "succeeded", "failed"} else "unknown"
        if item["state"] != "succeeded":
            return
        resources = [r for r in data.get("resources", [])
                     if str(r.get("state", "")).lower() == "succeeded" and r.get("resourceId")]
        if len(resources) != 1:
            item["state"] = "unknown"
            return
        resource_id = resources[0]["resourceId"]
        node = self.cli.node(job["project_id"], item["node_id"])
        matching = [r for r in node.get("resources", []) if r.get("resourceId") == resource_id
                    and r.get("submitId") == item["submit_id"] and r.get("type") == item["kind"]]
        if len(matching) != 1:
            item["state"] = "unknown"
            return
        item["resource_id"] = resource_id
        if download:
            self._save(job)
            self._download(job, item)

    def _download(self, job, item):
        folder = self.path(job["video_id"]).parent
        staging = folder / ".canvas-downloads" / item["submit_id"]
        staging.mkdir(parents=True, exist_ok=True)
        result = self.cli.call("resource", "download", item["resource_id"],
                               "--project-id", job["project_id"], "--output", str(staging), timeout=120)
        path = Path(result.get("path", "")).resolve()
        if (not path.is_relative_to(staging.resolve()) or not path.is_file()
                or type(result.get("size")) is not int or result["size"] <= 0
                or path.stat().st_size != result["size"]):
            raise CanvasError("invalid_download")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != result.get("sha256"):
            raise CanvasError("download_checksum_mismatch")
        ok, detail = validate_file(path, item["kind"], item["duration_s"])
        if not ok:
            item["state"] = "invalid"
            self._save(job)
            raise CanvasError("download_failed_media_validation", str(detail))
        ext = path.suffix.lower()
        allowed = {".mp4", ".mov", ".webm"} if item["kind"] == "video" else {".png", ".jpg", ".jpeg", ".webp"}
        if ext not in allowed:
            raise CanvasError("unsupported_download_format")
        target = folder / f"shot-{item['idx']:02d}.jimeng{ext}"
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise CanvasError("download_would_overwrite", "review the existing local file")
        temp = target.with_suffix(target.suffix + ".part")
        shutil.copyfile(path, temp)
        temp.replace(target)
        item.update(state="downloaded", file=target.name, sha256=sha, bytes=result["size"])
        self._save(job)

    def _manifest(self, job):
        sl = self._shot_list(job)
        folder = self.path(job["video_id"]).parent
        doc = build_manifest(job["video_id"], folder, len(sl["shots"]),
                             {s["idx"]: s["asset_type"] for s in sl["shots"]},
                             {s["idx"]: s["duration_s"] for s in sl["shots"]})
        write_manifest(doc, folder)
        return doc

    def status(self, video_id):
        job = read_state(self.path(video_id))
        self._identity(job)
        for item in job["shots"]:
            self._observe(job, item)
        return self.summary(job)

    def resume(self, video_id, wait_seconds=45):
        with generation_lock(self.base):
            job = read_state(self.path(video_id))
            self._identity(job)
            self._shot_list(job)
            for item in job["shots"]:
                self._observe(job, item, wait_seconds, download=True)
                self._save(job)
                if item["state"] in ACTIVE:
                    break
            self._manifest(job)
            return self.summary(job)

    @staticmethod
    def summary(job):
        return {"video_id": job["video_id"], "canvas_url": job.get("web_url"),
                "cli_version": job["account"]["version"], "credit_unit": "jimeng_credits",
                "quote": job.get("quote"), "approved_ceiling": job.get("approved_ceiling"),
                "reserved_credits": sum(i.get("authorized_credit_ceiling", 0) for i in job["shots"]),
                "complete": all(i["state"] in {"downloaded", "local"} for i in job["shots"]),
                "shots": [{k: i[k] for k in ("idx", "kind", "state", "node_id", "submit_id", "file")
                           if k in i} for i in job["shots"]]}
