"""Hypit build runner (F23): submit/observe/retrieve through the
pinned launcher. Observer detachment is NOT build failure — `status`
on the same build id is the truth; a new build is a new execution.
"""
import json
import re
import subprocess
from pathlib import Path

from ..domain.errors import ContractError

BUILD_ID_RE = re.compile(r'"?(build[-_][A-Za-z0-9]+|b[-_][A-Za-z0-9]+)"?')


class HypitBuildRunner:
    """runner(argv) -> CompletedProcess-like; real default goes through
    scripts/hypit.sh so the pinned bootstrap applies."""

    def __init__(self, runner=None):
        self.runner = runner or self._launcher

    @staticmethod
    def _launcher(argv):
        return subprocess.run(["./scripts/hypit.sh"] + argv + ["--json"],
                              capture_output=True, text=True,
                              timeout=600)

    def submit(self, svrun_path):
        """Start ONE build; the returned id is the recovery identity."""
        r = self.runner(["build", str(svrun_path)])
        if r.returncode != 0:
            raise ContractError("build_rejected", "svrun",
                                (r.stderr or r.stdout)[-200:])
        data = self._json(r.stdout)
        build_id = (data or {}).get("build") or \
            (data or {}).get("build_id") or \
            self._grep_id(r.stdout)
        if not build_id:
            raise ContractError("no_build_id", "stdout",
                                r.stdout[-200:])
        return {"build_id": build_id, "raw": data or r.stdout[-300:]}

    def observe(self, build_id):
        """→ {status: running|succeeded|failed|unknown, raw} — a
        timeout maps to 'unknown', never to 'failed'."""
        try:
            r = self.runner(["status", build_id])
        except subprocess.TimeoutExpired:
            return {"status": "unknown", "raw": "observer_timeout"}
        if r.returncode != 0:
            return {"status": "unknown", "raw": (r.stderr or "")[-200:]}
        data = self._json(r.stdout) or {}
        st = (data.get("status") or data.get("state") or "").lower()
        return {"status": {"succeeded": "succeeded",
                           "failed": "failed",
                           "cancelled": "failed"}.get(st, "running"),
                "raw": data}

    def retrieve(self, build_id, output_name, dest):
        """Fetch the named output to `dest`; the returned file is the
        deliverable — never assume it lives in the workspace."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = self.runner(["get", build_id, "--output", output_name,
                         "--to", str(dest)])
        if r.returncode != 0 or not dest.exists():
            raise ContractError("retrieve_failed", "build_id",
                                (r.stderr or r.stdout)[-200:])
        return dest

    @staticmethod
    def _json(text):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _grep_id(text):
        m = BUILD_ID_RE.search(text or "")
        return m.group(0).strip('"') if m else ""
