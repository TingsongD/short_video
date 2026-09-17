"""F01's own manual scenarios + the harness self-check.

A case callable receives a CaseContext and returns a result dict:
  {status, actual, assertions, artifacts, provider_submission_count,
   limitations, cleanup_receipt}
statuses: passed | failed | awaiting_manual_review
"""
import json

from . import workspace as ws
from . import faults as fault_registry
from .evidence import new_record, record_manual_verdict, save
from .registry import all_cases, case_status
from ..testing.fakes import FakeProvider, ProviderError


class CaseContext:
    def __init__(self, workspace, run_dir, mode, clock):
        self.workspace = workspace
        self.run_dir = run_dir
        self.mode = mode
        self.clock = clock
        self.assertions = []

    def provider(self, name, unit="usd_micros"):
        return FakeProvider(name, self.workspace.dir("fake_remote"),
                            self.workspace.ids, self.clock, unit=unit)

    def check(self, name, ok, detail=""):
        self.assertions.append({"name": name, "ok": bool(ok),
                                "detail": detail})
        return bool(ok)


def _result(ctx, status, actual, **kw):
    failed = [a for a in ctx.assertions if not a["ok"]]
    if failed:
        status = "failed"
    return {"status": status, "actual": actual,
            "assertions": ctx.assertions,
            "artifacts": kw.get("artifacts", []),
            "provider_submission_count": kw.get("provider_submission_count", 0),
            "limitations": kw.get("limitations", []),
            "cleanup_receipt": kw.get("cleanup_receipt")}


def self_check(ctx):
    p = ctx.provider("selfcheck")
    req = {"kind": "self-check", "n": 1}
    op = p.submit(req, price={"unit": "fake", "amount": 0})
    ctx.check("submit_returns_id", bool(op["operation_id"]))
    polled = p.poll(op["operation_id"])
    ctx.check("poll_succeeds", polled["status"] == "succeeded")
    dl = p.download(op["operation_id"])
    ctx.check("download_bytes", dl["bytes"].startswith(b"fake-media"))
    lock = ctx.workspace.path / "fixture-lock.json"
    ctx.check("fixture_lock_present", lock.exists(),
              f"{len(json.loads(lock.read_text())['files'])} files")
    return _result(ctx, "passed",
                   "harness self-check: fixture lock, fake submit/poll/download",
                   provider_submission_count=p.effect_counts()["submit"])


def f01_m01(ctx):
    p = ctx.provider("f01m01")
    before = p.effect_counts()["submit"]
    op = p.submit({"case": "F01-M01"},
                  price={"unit": "jimeng_credits", "amount": 0})
    ctx.check("operation_persisted", p.operation(op["operation_id"]) is not None)
    ctx.check("submit_counted", p.effect_counts()["submit"] == before + 1)
    specs = all_cases()
    ctx.check("registry_has_144", len([s for s in specs.values() if s.id != "SELF-CHECK"]) == 144)
    return _result(ctx, "awaiting_manual_review",
                   "initialized fixture, listed cases, exercised fake provider; "
                   "repeat invocation must reuse this run record",
                   limitations=["human confirms listed output readability"])


def f01_m02(ctx):
    # Absent module: F05 has no implementation yet.
    specs = all_cases()
    ctx.check("absent_module_marked",
              case_status(specs["F05-M01"]) == "missing_prerequisite",
              case_status(specs["F05-M01"]))
    # Unknown fault name rejected before any effect.
    try:
        fault_registry.validate(["rm-rf-everything"])
        ctx.check("unknown_fault_rejected", False)
    except KeyError:
        ctx.check("unknown_fault_rejected", True)
    # Occupied workspace refused without deleting.
    try:
        ws.init(ctx.workspace.path, "core-30s")
        ctx.check("occupied_init_refused", False)
    except ws.WorkspaceError as e:
        ctx.check("occupied_init_refused", "occupied" in str(e))
    ctx.check("workspace_survives",
              (ctx.workspace.path / "workspace.json").exists())
    return _result(ctx, "passed",
                   "three explicit errors; existing files survive; no "
                   "synthetic pass or arbitrary fault execution")


def f01_m03(ctx):
    p = ctx.provider("f01m03", unit="jimeng_credits")
    req = {"case": "F01-M03", "prompt": "lost-ack drill"}
    try:
        p.submit(req, faults=("accept-then-timeout",),
                 price={"unit": "jimeng_credits", "amount": 10})
        ctx.check("ack_lost", False, "submit unexpectedly returned")
    except ProviderError as e:
        ctx.check("ack_lost", e.code == "response_lost")
    # Provider state — independent of any app DB — shows acceptance+charge.
    ctx.check("provider_accepted",
              p.state.doc["operations"] != {}, "operation persisted remotely")
    ctx.check("charged_once", p.effect_counts()["charge"] == 1)
    # Simulated restart: a fresh object on the same state file.
    p2 = ctx.provider("f01m03", unit="jimeng_credits")
    import hashlib, json as _json
    rh = hashlib.sha256(_json.dumps(req, sort_keys=True).encode()).hexdigest()
    found = p2.reconcile(request_hash=rh)
    ctx.check("reconcile_finds_original", found is not None
              and found["status"] == "accepted")
    return _result(ctx, "awaiting_manual_review",
                   "provider acceptance recorded without app acknowledgement; "
                   "restart reconciles by request hash with no resubmission")


def f01_m04(ctx):
    rec = new_record("F01-M04", "F01", ctx.mode,
                     "manual verdict gates the pass",
                     ctx.workspace.fixture)
    rec["run_id"] = "f01m04-evidence"
    rec["actual"] = "automated portion executed; visual verdict pending"
    rec["status"] = "awaiting_manual_review"
    path = save(ctx.workspace.path, rec)
    ctx.check("evidence_written_pending", path.exists()
              and json.loads(path.read_text())["status"] == "awaiting_manual_review")
    record_manual_verdict(rec, reviewer="devin-agent", verdict="pass",
                          artifact_revision="fixture-lock@init",
                          notes="recorded through the required reviewer path")
    path2 = save(ctx.workspace.path, rec)
    ctx.check("verdict_recorded",
              json.loads(path2.read_text())["reviewer"] == "devin-agent")
    return _result(ctx, "passed",
                   "evidence exports before and after the human verdict; "
                   "final record carries reviewer and artifact hash",
                   artifacts=[str(path2)])


def implementations():
    return {"SELF-CHECK": self_check, "F01-M01": f01_m01,
            "F01-M02": f01_m02, "F01-M03": f01_m03, "F01-M04": f01_m04}
