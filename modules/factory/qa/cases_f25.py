from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
"""F25 manual scenarios: verified receipt + reuse, lost-ack reconcile,
conflict/checksum rejection, and the live authorized upload gate."""
import json

from .cases_f01 import CaseContext, _result
from ..delivery import DeliveryService, delivery_name
from ..store import Database
from ..testing.fakes import FakeDrive

FOLDER = "folder-authorized"


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    drive = FakeDrive(ctx.run_dir / f"{name}-remote.json")
    svc = DeliveryService(db, drive, effects=FixtureEffects(db, Executor(db)))
    final = ctx.run_dir / f"{name}.mp4"
    final.write_bytes(f"{name}-bytes".encode() * 500)
    name_final = delivery_name("exp1", "A", "hook", 1, 30)
    return db, drive, svc, final, name_final


def f25_m01(ctx: CaseContext):
    """Verify receipt fields, then re-deliver — identical remote file
    is reused, never duplicated."""
    db, drive, svc, final, name = _stack(ctx, "m01")
    r1 = svc.deliver("dlv-a", str(final), name, FOLDER)
    assert r1["status"] == "verified"
    body = json.loads(db.uow().records.get("delivery", "dlv-a")["body"])
    checks = {
        "receipt_file": body["drive_file_id"] == r1["file_id"],
        "receipt_md5": len(body["remote_md5"]) == 32,
        "receipt_sha": len(body["file_sha256"]) == 64,
        "receipt_parent": body["parent_folder_id"] == FOLDER,
        "receipt_link": body["drive_link"].endswith("/view"),
        "verified_at": bool(body["verified_at"]),
    }
    r2 = svc.deliver("dlv-b", str(final), name, FOLDER)
    checks["reused_no_duplicate"] = r2.get("reused") is True
    checks["one_remote_file"] = len(drive.doc["files"]) == 1
    checks["one_upload"] = drive.doc["uploads"] == 1
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f25_m02(ctx: CaseContext):
    """Lose the upload ack after remote creation, restart, resume —
    reconciled by content, no duplicate."""
    db, drive, svc, final, name = _stack(ctx, "m02")
    drive.lose_next_upload()
    r1 = svc.deliver("dlv-c", str(final), name, FOLDER)
    # "restart": fresh service over the persisted remote state
    svc2 = DeliveryService(db, FakeDrive(ctx.run_dir
                                         / "m02-remote.json"))
    r2 = svc2.reconcile("dlv-c")
    checks = {
        "first_recovered": r1["status"] == "verified",
        "reconcile_verified": r2["status"] == "verified",
        "no_duplicate": drive.doc["uploads"] == 1
        and len(drive.doc["files"]) == 1,
        "no_rerender": final.exists(),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f25_m03(ctx: CaseContext):
    """Same-name different-content file and missing MD5 — neither is
    accepted as delivery; local final preserved."""
    db, drive, svc, final, name = _stack(ctx, "m03")
    drive.plant(FOLDER, name, b"other content")
    r1 = svc.deliver("dlv-d", str(final), name, FOLDER)
    c1 = r1["status"] == "conflict" and drive.doc["uploads"] == 0
    db2 = Database(ctx.run_dir / "m03b.db")
    drive2 = FakeDrive(ctx.run_dir / "m03b-remote.json")
    drive2.set_no_md5()
    svc2 = DeliveryService(db2, drive2)
    r2 = svc2.deliver("dlv-e", str(final), name, FOLDER)
    c2 = r2["status"] == "unverified" \
        and "checksum_unavailable" in r2["problems"]
    checks = {"conflict_not_success": c1,
              "no_overwrite": c1,
              "checksum_gap_unverified": c2,
              "local_final_kept": final.exists()}
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f25_m04(ctx: CaseContext):
    """Upload one authorized test final to the real destination and
    verify name/size/parent/link — live case; never self-passes."""
    return _result(ctx, "awaiting_manual_review",
                   "live upload requires the authorized gdrive CLI "
                   "session and human link verification")


def implementations():
    return {"F25-M01": f25_m01, "F25-M02": f25_m02,
            "F25-M03": f25_m03, "F25-M04": f25_m04}
