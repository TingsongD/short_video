"""F08 manual scenarios: timing attribution, cursor resync, redaction,
health signals."""
from .cases_f01 import CaseContext, _result
from ..domain import Job
from ..events import (EventSubscription, ResyncRequired, health_report,
                      redact, timeline)
from ..execution import Executor
from ..store import Database

NOW = "2026-09-16T12:00:00Z"


def _db(ctx, name):
    return Database(ctx.run_dir / f"{name}.db")


def f08_m01(ctx: CaseContext):
    db = _db(ctx, "m08-1")
    # Deliberate, distinct stage delays on one job stream.
    events = [
        ("planned", "2026-09-16T10:00:00Z", {}),
        ("claimed", "2026-09-16T10:02:00Z", {}),
        ("dispatch_started", "2026-09-16T10:02:10Z", {}),
        ("accepted", "2026-09-16T10:02:20Z", {}),
        ("provider_finished", "2026-09-16T10:10:00Z",
         {"provider_finished_at": "2026-09-16T10:09:50Z"}),
        ("downloaded", "2026-09-16T10:11:00Z", {}),
        ("review_started", "2026-09-16T10:11:10Z", {}),
        ("review_finished", "2026-09-16T10:12:10Z", {}),
    ]
    with db.uow() as u:
        u.jobs.put(Job(schema_version="job.v1", id="timed",
                       created_at=NOW, logical_key="lk-t", phase="p",
                       status="ready"))
        for t, at, body in events:
            u.conn.execute(
                "INSERT INTO events(stream,type,body,created_at) "
                "VALUES(?,?,?,?)",
                ("job:timed", t, __import__("json").dumps(body), at))
    rows = [dict(r) for r in db.conn.execute(
        "SELECT * FROM events WHERE stream='job:timed' ORDER BY seq")]
    import json as _j
    for r in rows:
        r["body"] = _j.loads(r["body"])
    t = timeline(rows)
    d = t["durations"]
    ctx.check("queue_wait_attributed", d["queue_wait_s"] == 120.0)
    ctx.check("provider_elapsed_attributed",
              abs(d["provider_elapsed_s"] - 450.0) < 1)
    ctx.check("collection_delay", d["collection_delay_s"] == 60.0)
    ctx.check("review_time", d["review_s"] == 60.0)
    ctx.check("no_double_count",
              d["queue_wait_s"] + d["provider_elapsed_s"]
              + d["collection_delay_s"] <= d["wall_clock_s"])
    db.close()
    return _result(ctx, "passed",
                   "queue 120s, provider 450s (reported finish), collect "
                   "60s, review 60s — attributed to their real stages")


def f08_m02(ctx: CaseContext):
    db = _db(ctx, "m08-2")
    sub = EventSubscription(db)
    with db.uow() as u:
        u.jobs.put(Job(schema_version="job.v1", id="obs",
                       created_at=NOW, logical_key="lk-o", phase="p",
                       status="ready"))
        u.events.append("job:obs", "planned", {})
    evs = sub.replay("job:obs")
    cursor = evs[-1]["seq"]
    # Observer "disconnects"; work advances meanwhile.
    with db.uow() as u:
        for t in ("claimed", "dispatch_started", "accepted",
                  "provider_finished", "downloaded"):
            u.events.append("job:obs", t, {})
    missed = sub.replay("job:obs", cursor)
    ctx.check("replay_once", len(missed) == 5
              and missed[0]["type"] == "claimed")
    snap = sub.snapshot("job:obs")
    ctx.check("snapshot_agrees", snap["projection"]["id"] == "obs")
    db.close()
    return _result(ctx, "passed",
                   "reconnect with last cursor replays exactly the missed "
                   "events once; snapshot projection agrees with history")


def f08_m03(ctx: CaseContext):
    fake_token = "ya29" + "." + "faketoken0123456789"
    doc = {"provider_error": f"HTTP 401 {fake_token}",
           "signed_url": "https://x.storage/?sig=0123456789abcdef0"
                          "&Expires=999999",
           "safe": {"artifact": "art:abc", "attempt": "att:j:1"}}
    out = redact(doc)
    import json
    flat = json.dumps(out)
    ctx.check("oauth_token_gone", "faketoken" not in flat)
    ctx.check("signed_url_params_gone", "sig=0123" not in flat
              and "Expires=9" not in flat)
    ctx.check("safe_refs_survive", out["safe"]["artifact"] == "art:abc")
    return _result(ctx, "passed",
                   "credential/token/signed-URL material absent from "
                   "exported diagnostics; artifact/attempt refs intact")


def f08_m04(ctx: CaseContext):
    db = _db(ctx, "m08-4")
    sub = EventSubscription(db)
    with db.uow() as u:
        u.jobs.put(Job(schema_version="job.v1", id="stale",
                       created_at=NOW, logical_key="lk-s", phase="p",
                       status="ready"))
        for i in range(10):
            u.events.append("job:stale", f"e{i}", {})
    sub.retain("job:stale", keep_last_n=3)
    try:
        sub.replay("job:stale", cursor=1)
        ctx.check("resync_offered", False)
    except ResyncRequired as e:
        ctx.check("resync_offered",
                  "snapshot" in str(e) and e.snapshot_seq > 0)
    # Stale lease + unknown attempt visible in health with owner+action.
    db.conn.execute(
        "UPDATE jobs SET lease_owner='w-old', lease_expires='2000-01-01',"
        " status='running' WHERE id='stale'")
    p = ctx.provider("m08-4")
    ex = Executor(db, p)
    aid = ex.prepare("stale", 1, {"p": 1})
    ex._set_status(aid, "unknown", "drill")
    rep = health_report(db, now="2026-09-16T15:00:00Z")
    kinds = {s["signal"] for s in rep["signals"]}
    ctx.check("health_names_owner",
              "stale_lease" in kinds and "unknown_attempt" in kinds)
    db.close()
    return _result(ctx, "passed",
                   "expired cursor gets explicit resync instructions; "
                   "health report identifies unresolved work + owner")


def implementations():
    return {"F08-M01": f08_m01, "F08-M02": f08_m02,
            "F08-M03": f08_m03, "F08-M04": f08_m04}
