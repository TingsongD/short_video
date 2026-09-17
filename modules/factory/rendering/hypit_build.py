"""Pinned Hypit 0.1.8 envelopes; durable workspace-scoped local builds."""
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

from ..composition.gate import HypitGate
from ..domain.errors import ContractError
from ..providers.state import DurableState

LAUNCHER = Path(__file__).resolve().parents[3] / "scripts/hypit.sh"


class HypitBuildRunner:
    def __init__(self, runner=None):
        self.runner = runner or self._launcher

    @staticmethod
    def _launcher(argv):
        return subprocess.run([str(LAUNCHER)] + argv + ["--json"], capture_output=True,
                              text=True, timeout=600)

    def submit(self, svrun_path):
        source = Path(svrun_path).resolve()
        workspace = source.parent
        if not source.is_file():
            raise ContractError("run_missing", "svrun")
        # One receipt per frozen run content. RenderService owns new revision IDs.
        files = [source, *workspace.glob("*.svml"), *workspace.glob("*.svs"), *workspace.glob("assets/*")]
        fingerprint = {str(p.relative_to(workspace)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
        profile = workspace / "hypit.runtime.json"
        if profile.is_file():
            fingerprint[profile.name] = hashlib.sha256(profile.read_bytes()).hexdigest()
        digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        state = DurableState(workspace / ".factory-build.json")
        if state:
            if state["run_hash"] != digest:
                raise ContractError("build_revision_changed", "svrun")
            if state.get("build_id"):
                return {"build_id": state["build_id"], "workspace": str(workspace)}
            return self._recover(state, workspace)
        gate = HypitGate(runner=self.runner)
        check = gate.check(source)
        plan = gate.plan(source)
        if not check["ok"] or not plan["ok"]:
            raise ContractError("local_plan_required", "svrun")
        state.update(run_hash=digest, workspace=str(workspace), title="factory-" + str(uuid.uuid4()), status="submitting")
        state.flush()
        try:
            result = self.runner(["build", str(source), "--workspace", str(workspace), "--title", state["title"]])
        except subprocess.TimeoutExpired:
            raise ContractError("build_submission_unresolved", "svrun") from None
        doc = self._json(result.stdout)
        if result.returncode or doc.get("format") != "hypit.cli-build@1":
            raise ContractError("build_submission_unresolved", "svrun")
        build = doc.get("build")
        if not isinstance(build, dict) or not isinstance(build.get("id"), str):
            raise ContractError("no_build_id", "svrun")
        state.update(build_id=build["id"], status="submitted")
        state.flush()
        return {"build_id": build["id"], "workspace": str(workspace)}

    def _recover(self, state, workspace):
        candidates = set()
        result = self.runner(["builds", "--workspace", str(workspace)])
        doc = self._json(result.stdout)
        if result.returncode == 0 and doc.get("format") == "hypit.cli-builds@1":
            candidates.update(b["id"] for b in doc.get("builds", []) if b.get("title") == state["title"])
        active = self.runner(["activity", "--workspace", str(workspace)])
        doc = self._json(active.stdout)
        if active.returncode == 0 and doc.get("format") == "hypit.cli-activity@1":
            for build in doc.get("builds", []):
                result = self.runner(["status", build["id"], "--workspace", str(workspace)])
                status = self._json(result.stdout).get("build") or {}
                if status.get("title") == state["title"]:
                    candidates.add(build["id"])
        if len(candidates) != 1:
            raise ContractError("build_submission_unresolved", "workspace")
        state.update(build_id=candidates.pop(), status="reconciled")
        state.flush()
        return {"build_id": state["build_id"], "workspace": str(workspace)}

    def observe(self, build_id, workspace):
        try:
            result = self.runner(["status", build_id, "--workspace", str(workspace)])
        except subprocess.TimeoutExpired:
            return {"status": "unknown", "reason": "observer_timeout"}
        doc = self._json(result.stdout)
        build = doc.get("build") or {}
        if doc.get("format") != "hypit.cli-status@1" or build.get("id") != build_id:
            return {"status": "unknown", "reason": "invalid_status"}
        work, final = build.get("work", {}), build.get("result", {})
        status = "unknown"
        if work.get("state") == "done":
            if work.get("outcome") == "complete" and final.get("state") == "complete":
                status = "succeeded"
            elif work.get("outcome") in ("failed", "cancelled"):
                status = "failed"
        elif work.get("state") in ("submitting", "working"):
            status = "running"
        return {"status": status}

    def retrieve(self, build_id, output_name, dest, workspace):
        dest = Path(dest).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = self.runner(["get", build_id, "--output", output_name, "--to", str(dest), "--workspace", str(workspace)])
        doc = self._json(result.stdout)
        if (result.returncode or not dest.is_file() or doc.get("format") != "hypit.cli-get@1"
                or doc.get("build") != build_id or doc.get("output") != output_name or doc.get("path") != str(dest)):
            raise ContractError("retrieve_failed", "build_id")
        return dest

    @staticmethod
    def _json(text):
        try:
            doc = json.loads(text)
            return doc if isinstance(doc, dict) else {}
        except (ValueError, TypeError):
            return {}
