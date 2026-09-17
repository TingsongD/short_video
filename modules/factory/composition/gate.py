"""Hypit check/plan gate (F22): run the pinned launcher, parse its
verdict, and reject any hosted generation/provider work appearing in a
supposedly local composition plan. Compile artifacts only — this gate
never submits a build.
"""
import json
import re
import subprocess

from ..domain.errors import ContractError
from .compiler import ALLOWED_IMPORTS

IMPORT_RE = re.compile(r'<import\s+as="[^"]+"\s+from="([^"]+)"')
IMPORT_SRC_RE = re.compile(r'<import\s+as="[^"]+"\s+source="([^"]+)"')

# plan-step kinds that would mean a paid/hosted call inside composition
HOSTED_STEP_KINDS = {"generation", "provider", "hosted", "upload",
                     "publish"}

# capabilities a local composition plan may request — anything outside
# this vocabulary is hosted/provider work and fails the gate
LOCAL_CAPABILITY_PREFIXES = (
    "@hypit/media-pipeline@1", "@hypit/render-hyperframes@1",
    "@hypit/film@1", "@hypit/media-track@1",
    "@hypit/typography-track@1", "@hypit/timeline-author@1",
    "@hypit/spatial@1", "@hypit/media@1", "@hypit/run-markup@1",
    "@hypit/svs@1", "@hypit/audio-track@1")


def audit_imports(svml_text):
    """Every import must be in the declared local vocabulary. An
    unexpected namespace (generation/provider components) is a
    compile-gate failure, not a warning."""
    found = set(IMPORT_RE.findall(svml_text)) | \
        set(IMPORT_SRC_RE.findall(svml_text))
    bad = sorted(found - ALLOWED_IMPORTS)
    return [{"code": "hosted_component", "at": "svml.import",
             "detail": b} for b in bad]


def audit_plan(plan):
    if not isinstance(plan, dict) or plan.get("format") != "hypit.cli-plan@1" or plan.get("ok") is not True:
        return [{"code": "malformed_plan", "at": "plan", "detail": "Expected pinned CLI plan envelope"}]
    needs = plan.get("needs")
    if (not isinstance(needs, list) or type(plan.get("requestCount")) is not int
            or len(needs) != plan["requestCount"] or plan.get("requestIssueCount", 0) != 0):
        return [{"code": "incomplete_plan", "at": "plan", "detail": "Every demanded request must be inspected"}]
    diags = []
    for need in needs:
        cap = need.get("capability", "") if isinstance(need, dict) else ""
        if cap.split("#")[0] not in LOCAL_CAPABILITY_PREFIXES:
            diags.append({"code": "hosted_step", "at": "plan.need", "detail": cap or "no_capability"})
    if any(plan.get(k, 0) for k in ("providerRequestCount", "unresolvedRequestCount", "unsupportedRequestCount")):
        diags.append({"code": "hosted_step", "at": "plan", "detail": "Nonlocal or unresolved requests"})
    if plan.get("preflight", {}).get("ok") is False:
        diags.append({"code": "preflight_failed", "at": "plan", "detail": "Runtime readiness failed"})
    return diags


class HypitGate:
    """Runs `scripts/hypit.sh check|plan` through the pinned launcher.
    Runner is injectable for offline tests: callable(argv) ->
    CompletedProcess-like {returncode, stdout, stderr}."""

    def __init__(self, runner=None):
        self.runner = runner or self._launcher

    @staticmethod
    def _launcher(argv):
        # --json follows the subcommand+source (hypit CLI convention)
        return subprocess.run(["./scripts/hypit.sh"] + argv + ["--json"],
                              capture_output=True, text=True,
                              timeout=120)

    def check(self, svml_path):
        from pathlib import Path
        r = self.runner(["check", str(svml_path), "--workspace", str(Path(svml_path).resolve().parent)])
        if r.returncode != 0:
            return {"ok": False,
                    "diagnostics": [{"code": "check_failed",
                                     "at": str(svml_path),
                                     "detail": (r.stdout or r.stderr)[-300:]}]}
        doc = self._parse(r.stdout)
        return {"ok": doc.get("format") == "hypit.cli-check@1" and doc.get("ok") is True, "report": doc}

    def plan(self, svrun_path):
        from pathlib import Path
        r = self.runner(["plan", str(svrun_path), "--workspace", str(Path(svrun_path).resolve().parent)])
        if r.returncode != 0:
            return {"ok": False,
                    "diagnostics": [{"code": "plan_failed",
                                     "at": str(svrun_path),
                                     "detail": (r.stdout or r.stderr)[-300:]}]}
        plan = self._parse(r.stdout)
        diags = audit_plan(plan if isinstance(plan, dict) else {})
        return {"ok": not diags, "plan": plan, "diagnostics": diags}

    @staticmethod
    def _parse(text):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return {"raw": (text or "")[-500:]}
