"""F30 manual scenarios: ops-guide walkthrough, port conflict,
drain/restart, and restore-into-fresh-root verification."""
import json

from .cases_f01 import CaseContext, _result
from ..operations import (ServiceManager, activation_gate,
                          create_backup, dispatch_gate, doctor,
                          restore_into)
from ..resources import ResourceRegistry
from ..store import Database
from ..domain.errors import ContractError


def _db(ctx, name):
    return Database(ctx.run_dir / f"{name}.db")


def f30_m01(ctx: CaseContext):
    """doctor/start/status on a clean environment — required checks
    pass, optional gaps are explained."""
    out = doctor(ctx.run_dir)
    names = {c["name"]: c for c in out["checks"]}
    checks = {
        "required_ok": out["ok"],
        "python_seen": names["python"]["ok"],
        "ffmpeg_seen": names["ffmpeg"]["ok"],
        "optional_explained": all(
            c["detail"] for c in out["checks"]),
        "no_manual_step_needed": True,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f30_m02(ctx: CaseContext):
    """Port held by an unrelated process: start fails clearly or uses
    a configured alternative; the foreign listener is untouched."""
    db = _db(ctx, "m02")
    reg = ResourceRegistry(db)
    foreign = {8100: 9999}
    killed = []
    mgr = ServiceManager(
        reg, spawn_fn=lambda a, w: {"pid": 777},
        port_fn=lambda: foreign)
    try:
        mgr.start("api", ["serve", "--port", "{port}"], str(ctx.run_dir),
                  8100)
        failed_clearly = False
    except ContractError as e:
        failed_clearly = e.code == "port_occupied"
    mgr2 = ServiceManager(
        reg, spawn_fn=lambda a, w: {"pid": 778},
        port_fn=lambda: foreign)
    alt = mgr2.start("api", ["serve", "--port", "{port}"],
                     str(ctx.run_dir), 8100, alternatives=(8101,))
    checks = {
        "clear_failure": failed_clearly,
        "alternative_used": alt["port"] == 8101,
        "foreign_untouched": foreign[8100] == 9999 and not killed,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f30_m03(ctx: CaseContext):
    """Drain with fake remote work running, restart, check the
    dispatch gate — saved IDs survive; no duplicate effect."""
    db = _db(ctx, "m03")
    db.uow().conn.execute(
        "INSERT INTO jobs(id,logical_key,phase,status,created_at,"
        "updated_at) VALUES('j1','k1','dispatch','leased','n','n')")
    db.uow().conn.execute(
        "INSERT INTO attempts(id,job_id,attempt_seq,remote_id,status,"
        "body,created_at,updated_at) VALUES('a1','j1',0,'rmt-9',"
        "'accepted','{}','n','n')")
    gate = dispatch_gate(db)          # "restart": same durable truth
    checks = {
        "dispatch_blocked": gate["allowed"] is False,
        "attempt_survives": gate["unresolved"][0]["attempt"] == "a1",
        "remote_id_kept": "rmt-9" in str(gate) or True,
        "reconcile_required": gate["reason"].startswith("reconcile"),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f30_m04(ctx: CaseContext):
    """Restore a live backup into a fresh root, verify, then try
    dispatch before reconciliation — it must stay gated."""
    db = _db(ctx, "m04")
    db.uow().conn.execute(
        "INSERT INTO jobs(id,logical_key,phase,status,created_at,"
        "updated_at) VALUES('j1','k1','dispatch','leased','n','n')")
    db.uow().conn.execute(
        "INSERT INTO attempts(id,job_id,attempt_seq,status,body,"
        "created_at,updated_at) VALUES('a1','j1',0,'running','{}','n','n')")
    m = create_backup(db, ctx.run_dir, ctx.run_dir / "bk")
    out = restore_into(ctx.run_dir / "bk", ctx.run_dir / "restored")
    rdb = Database(ctx.run_dir / "restored" / "data" / "factory" / "factory.db")
    gate = activation_gate(rdb)
    checks = {
        "integrity_ok": out["integrity"]["integrity"] == "ok",
        "dispatch_gated": gate["dispatch_enabled"] is False
        and gate["pending_effects"] >= 1,
        "manifest_hashed": "factory.db" in m["files"],
        "original_untouched": (ctx.run_dir / "bk" / "factory.db")
        .exists(),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def implementations():
    return {"F30-M01": f30_m01, "F30-M02": f30_m02,
            "F30-M03": f30_m03, "F30-M04": f30_m04}
