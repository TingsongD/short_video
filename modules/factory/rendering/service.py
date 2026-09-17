"""Render service (F23): register an owned build before execution;
dispatch by declared renderer; observe the same build (timeout ≠
failure); retrieve the actual returned file; register it atomically.
"""
import hashlib
import json
import subprocess
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import RenderBuild, content_hash
from .ffmpeg_fast import FastPathRenderer, RenderTimeout
from .hypit_build import HypitBuildRunner


class RenderService:
    def __init__(self, db, artifacts, workspace_root,
                 fast_renderer=None, hypit=None):
        self.db = db
        self.artifacts = artifacts
        self.root = Path(workspace_root)
        self.fast = fast_renderer or FastPathRenderer()
        self.hypit = hypit or HypitBuildRunner()

    # --------------------------------------------------------- build --

    def register(self, build_id, composition, now=""):
        """Persist the owned build BEFORE any execution."""
        ws = self.root / build_id
        b = RenderBuild(schema_version="render_build.v1", id=build_id,
                        created_at=now,
                        composition_id=composition["id"],
                        composition_hash=composition.get(
                            "content_hash", ""),
                        variant_key=composition["variant_key"],
                        renderer=composition["renderer"],
                        workspace=str(ws), status="registered")
        b.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(b)
        return b

    def dispatch(self, build_id, segments, captions, audio, clock,
                 svrun_path=None, inputs=None, now=""):
        """Run the declared renderer. ffmpeg_fast renders locally;
        hypit submits ONE build and stores its remote id."""
        b = self._build(build_id)
        ws = Path(b["workspace"])
        ws.mkdir(parents=True, exist_ok=True)
        def bound_media(items):
            return [{**item,"sha256":hashlib.sha256(Path(item["src"]).read_bytes()).hexdigest()} for item in items]
        inputs_hash = content_hash({"segments":bound_media(segments), "audio":bound_media(audio),
                                   "captions":captions,"clock":clock,"extra":inputs,
                                   "composition":b["composition_hash"],"renderer":b["renderer"],"version":"render.v3"})
        if b.get("inputs_hash") and b["inputs_hash"] != inputs_hash:
            raise ContractError("render_input_revision_mismatch", "build_id")
        if b["status"] in ("succeeded","collected"):
            return {"status":b["status"],"path":str(ws/"final.mp4"),"sha256":b["output_sha256"]}
        self._set(build_id, status="running", inputs_hash=inputs_hash)
        if b["renderer"] == "ffmpeg_fast":
            try:
                final = self.fast.render(
                    ws, segments, captions, audio, clock,
                    final_name="final.mp4",
                    progress=b.get("progress") or None)
            except RenderTimeout as e:
                self._set(build_id, status="observer_lost",
                          problem=str(e))
                return {"status": "observer_lost"}
            except RuntimeError as e:
                self._set(build_id, status="failed", problem=str(e))
                return {"status": "failed", "problem": str(e)}
            return self._finalize_local(build_id, final)
        # hypit path
        if b.get("remote_build_id"):
            return {"status": "running", "remote_build_id": b["remote_build_id"]}
        out = self.hypit.submit(svrun_path or
                                ws / "render.svrun")
        self._set(build_id, status="running",
                  remote_build_id=out["build_id"], hypit_workspace=out["workspace"])
        return {"status": "running",
                "remote_build_id": out["build_id"]}

    def _finalize_local(self, build_id, final):
        sha = hashlib.sha256(Path(final).read_bytes()).hexdigest()
        self._set(build_id, status="succeeded", output_sha256=sha)
        return {"status": "succeeded", "path": str(final),
                "sha256": sha}

    # -------------------------------------------------------- observe --

    def observe(self, build_id):
        """Observer timeout is UNKNOWN, not failed — same build, same
        remote id; we never submit a second build implicitly."""
        b = self._build(build_id)
        if b["renderer"] == "ffmpeg_fast":
            return {"status": b["status"]}
        obs = self.hypit.observe(b["remote_build_id"], b["hypit_workspace"])
        if obs["status"] == "unknown":
            self._set(build_id, status="observer_lost",
                      problem="observer_timeout")
        elif obs["status"] == "succeeded":
            self._set(build_id, status="succeeded")
        elif obs["status"] == "failed":
            self._set(build_id, status="failed",
                      problem=json.dumps(obs.get("raw"))[:200])
        return obs

    def collect(self, build_id, now=""):
        """Retrieve the actual returned final, probe it, register the
        artifact atomically. Never assumes the workspace location."""
        b = self._build(build_id)
        if b["status"] != "succeeded":
            raise ContractError("not_collectable", "status",
                                b["status"])
        if b["renderer"] == "hypit":
            dest = Path(b["workspace"]) / "returned-final.mp4"
            final = self.hypit.retrieve(b["remote_build_id"],
                                        b["output_name"], dest, b["hypit_workspace"])
        else:
            final = Path(b["workspace"]) / "final.mp4"
        data = Path(final).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if b["output_sha256"] and sha != b["output_sha256"]:
            raise ContractError("output_mismatch", "sha256",
                                f"{sha[:12]} != recorded")
        art = self.artifacts.intake_bytes(
            data, provenance="generated_other",
            source_key=f"render:{build_id}",
            source_detail=f"{b['renderer']} final",
            requested_kind="video")
        self._set(build_id, status="collected",
                  output_artifact_id=art.id, output_sha256=sha,
                  finished_at=now)
        return {"artifact_id": art.id, "sha256": sha}

    # --------------------------------------------------------- state --

    def _build(self, build_id):
        row = self.db.uow().records.get("renderbuild", build_id)
        if row is None:
            raise ContractError("unknown_build", "build_id", build_id)
        body=json.loads(row["body"])
        from ..operations.paths import restored_path
        for key in ('workspace','hypit_workspace'):
            if body.get(key):body[key]=str(restored_path(self.db,body[key]))
        return body

    def _set(self, build_id, **fields):
        row = self.db.uow().records.get("renderbuild", build_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='renderbuild'"
                " AND id=? AND revision=?",
                (json.dumps(body), build_id, row["revision"]))
