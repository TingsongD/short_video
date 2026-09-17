"""F03 manual scenarios: durable store, CAS, crash recovery, restore."""
import os

from .cases_f01 import CaseContext, _result
from ..domain import ContractError, ExperimentRevision, Job, Attempt
from ..domain.records import content_hash
from ..store import Database, NewerDatabaseError, StaleRevisionError, backup


def _exp(eid, rev=1, status="draft"):
    return ExperimentRevision(
        schema_version="experiment_revision.v1", id=f"er:{eid}:{rev}",
        created_at="2026-09-16T00:00:00Z", experiment_id=eid,
        revision=rev, status=status)


def f03_m01(ctx: CaseContext):
    path = ctx.workspace.dir("store") / "m01.db"
    db = Database(path)
    with db.uow() as u:
        u.records.put(_exp("m01"))
        u.events.append("experiment:m01", "created", {"v": 1})
    db.close()                                   # "service restart"
    db = Database(path)
    row = db.uow().records.get("experimentrevision", "er:m01:1")
    evs = db.uow().events.since("experiment:m01")
    ctx.check("ids_survive_restart", row is not None
              and row["revision"] == 1 and row["status"] == "draft")
    ctx.check("events_match_history",
              len(evs) == 1 and evs[0]["type"] == "created")
    db.close()
    return _result(ctx, "passed",
                   "experiment + event durable across restart; projection "
                   "matches history")


def f03_m02(ctx: CaseContext):
    path = ctx.workspace.dir("store") / "m02.db"
    db = Database(path)
    with db.uow() as u:
        u.records.put(_exp("m02"))
    row = db.uow().records.get("experimentrevision", "er:m02:1")
    e = _exp("m02"); e.status = "accepted"; e.content_hash = "a" * 64
    with db.uow() as u:
        u.records.put(e, expected_version=row["version"])
    try:
        with db.uow() as u:
            u.records.put(e, expected_version=row["version"])
        ctx.check("stale_rejected", False)
    except StaleRevisionError:
        ctx.check("stale_rejected", True)
    cur = db.uow().records.get("experimentrevision", "er:m02:1")
    ctx.check("winner_not_overwritten", cur["status"] == "accepted")
    db.close()
    return _result(ctx, "passed",
                   "second writer on same expected version gets "
                   "stale-revision conflict; first write intact")


def f03_m03(ctx: CaseContext):
    path = ctx.workspace.dir("store") / "m03.db"
    db = Database(path)
    # Crash AFTER committing intent+outbox, BEFORE dispatch.
    with db.uow() as u:
        u.intents.create("intent:crash", "rh-123", "provider_submit",
                         {"prompt": "x"})
        u.outbox.enqueue("intent:crash", "provider_submit",
                         {"request_hash": "rh-123"})
    db.close()
    db = Database(path)                          # restart
    found = db.uow().intents.by_request_hash("rh-123", "provider_submit")
    ctx.check("committed_intent_visible", len(found) == 1
              and found[0]["status"] == "prepared")
    ctx.check("outbox_pending", len(db.uow().outbox.pending()) == 1)
    # A rolled-back attempt must leave no partial children.
    try:
        with db.uow() as u:
            u.jobs.put(Job(schema_version="job.v1", id="j:c",
                           created_at="2026-09-16T00:00:00Z",
                           logical_key="lk-c", phase="p", status="ready"))
            u.attempts.put(Attempt(schema_version="attempt.v1",
                                   id="at:c", created_at="2026-09-16T00:00:00Z",
                                   job_id="j:c", attempt_seq=1))
            raise RuntimeError("crash")
    except RuntimeError:
        pass
    ctx.check("no_partial_children", db.uow().jobs.get("j:c") is None
              and db.conn.execute(
                  "SELECT COUNT(*) FROM attempts").fetchone()[0] == 0)
    db.close()
    return _result(ctx, "awaiting_manual_review",
                   "committed intent reconcilable after restart; rolled-back"
                   " transaction left no partial rows",
                   limitations=["human kills a real worker process in F34"])


def f03_m04(ctx: CaseContext):
    path = ctx.workspace.dir("store") / "m04.db"
    db = Database(path)
    with db.uow() as u:
        u.records.put(_exp("m04"))
        u.events.append("experiment:m04", "created", {})
    dest = ctx.workspace.dir("store") / "m04-copy.db"
    info = backup.backup(path, dest)
    ctx.check("restore_integrity", info["integrity"] == "ok")
    ctx.check("schema_version", info["schema_version"] == 2)
    # Simulate a database from the future.
    conn = Database(dest)
    conn.conn.execute(
        "UPDATE meta SET value='99' WHERE key='schema_version'")
    conn.conn.commit()
    conn.close()
    try:
        Database(dest)
        ctx.check("newer_version_refused", False)
    except NewerDatabaseError:
        ctx.check("newer_version_refused", True)
    db.close()
    return _result(ctx, "passed",
                   "backup of live DB restores with integrity ok; v99 "
                   "database refused before any write")


def implementations():
    return {"F03-M01": f03_m01, "F03-M02": f03_m02,
            "F03-M03": f03_m03, "F03-M04": f03_m04}
