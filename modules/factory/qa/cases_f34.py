"""F34 manual scenarios: operator journeys, checkpoint crashes,
concurrency/disconnect pressure, and stage timing evidence.

The deterministic failure matrix lives in tests/test_factory_e2e.py
(J01/J02/J03/J04/J08, lost-ack at submit/upload/publish, budget cap,
global capacities, cache parity, no-network audit, owned cleanup).
M02 and M04 implement their automatable cores here; M01/M03 are
human observation flows."""
from .cases_f01 import CaseContext, _result
from ..delivery.service import DeliveryService
from ..domain.records import Job
from ..events.timing import timeline
from ..scheduler.scheduler import Scheduler
from ..store import Database
from ..testing.fakes import FakeDrive

NOW = "2026-09-17T12:00:00+00:00"


def f34_m01(ctx: CaseContext):
    """J01/J02/J04 through the operator UI — inspect all four outputs
    and the fake call ledger."""
    return _result(ctx, "awaiting_manual_review",
                   "operator UI walkthrough is human; headless J01 "
                   "seed→4-outputs, J02 long-reference and J04 "
                   "canvas+vertex routes are verified by "
                   "tests/test_factory_e2e.py (14 tests)")


def f34_m02(ctx: CaseContext):
    """Checkpoint crash around upload: kill after the remote put but
    before the ack is persisted; the restarted service must reconcile
    to verified with exactly one remote effect."""
    db = Database(ctx.run_dir / "m02.db")
    src = ctx.run_dir / "final.mp4"
    src.write_bytes(b"final-bytes" * 500)
    drive = FakeDrive(ctx.run_dir / "drive.json")
    drive.doc["lost_next"] = True                 # kill after put, ack lost
    DeliveryService(db, drive).deliver(
        "del-1", str(src), "f.mp4", "folder-1", now=NOW)
    # restart — new service instance over the same remote world
    out = DeliveryService(db, FakeDrive(ctx.run_dir / "drive.json")
                          ).reconcile("del-1", now=NOW)
    body = db.uow().records.get("delivery", "del-1")
    checks = {
        "verified_after_restart": out["status"] == "verified",
        "one_remote_effect": drive.doc["uploads"] == 1,
        "artifact_not_recreated":
            body["body"].find('"file_sha256"') != -1,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"uploads={drive.doc['uploads']} status={out['status']}",
                   detail=checks)


def f34_m03(ctx: CaseContext):
    """Concurrent experiments under throttles and browser disconnect —
    capacities stay global, no wait depends on a UI connection."""
    return _result(ctx, "awaiting_manual_review",
                   "browser disconnect/pressure is human; global "
                   "capacity across workers and throttled claims are "
                   "verified by test_jimeng_capacity_is_global and "
                   "the F06 scheduler suite")


def f34_m04(ctx: CaseContext):
    """Stage timing evidence: a claimed job's event stream must
    attribute queue wait and dispatch durations separately — long
    delays must have attributable causes, not silent gaps."""
    db = Database(ctx.run_dir / "m04.db")
    s = Scheduler(db, worker_id="w1")
    s.submit_plan([Job(schema_version="job.v1", id="j-a",
                       created_at=NOW, logical_key="lk-a",
                       phase="generate_jimeng"),
                   Job(schema_version="job.v1", id="j-b",
                       created_at=NOW, logical_key="lk-b",
                       phase="generate_jimeng",
                       depends_on=["j-a"])])
    c1 = s.claim()
    s.complete(c1["id"], c1["fencing_token"])
    c2 = s.claim()
    s.complete(c2["id"], c2["fencing_token"])
    rows = db.uow().conn.execute(
        "SELECT * FROM events ORDER BY seq").fetchall()
    streams = {}
    for r in rows:
        streams.setdefault(r["stream"], []).append(dict(r))
    timelines = [timeline(evs) for evs in streams.values()
                 if any(e["type"] == "claimed" for e in evs)]
    keys = set().union(*(t["durations"].keys() for t in timelines))
    checks = {
        "timelines_found": len(timelines) >= 2,
        "queue_wait_attributed": "queue_wait_s" in keys,
        "dispatch_attributed": "dispatch_s" in keys,
        "nonnegative": all(v >= 0 for t in timelines
                           for v in t["durations"].values()
                           if v is not None),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"streams={len(streams)} keys={sorted(keys)}",
                   detail=checks)


def implementations():
    return {"F34-M01": f34_m01, "F34-M02": f34_m02,
            "F34-M03": f34_m03, "F34-M04": f34_m04}
