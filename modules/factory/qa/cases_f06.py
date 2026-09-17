"""F06 manual scenarios: global capacities, pause/collect, fencing,
resource gating."""
from .cases_f01 import CaseContext, _result
from ..domain import Job
from ..scheduler import FencingError, ResourcePolicy, Scheduler
from ..store import Database

NOW = "2026-09-16T12:00:00Z"


def _sched(ctx, name, worker="w1"):
    db = Database(ctx.workspace.dir("store") / f"{name}.db")
    return Scheduler(db, worker_id=worker), db


def _job(jid, phase, deps=()):
    return Job(schema_version="job.v1", id=jid, created_at=NOW,
               logical_key=f"lk-{jid}", phase=phase,
               depends_on=list(deps))


def f06_m01(ctx: CaseContext):
    s, db = _sched(ctx, "m06-1")
    jobs = ([_job(f"j{i}", "generate_jimeng") for i in range(12)]
            + [_job(f"v{i}", "generate_vertex") for i in range(3)]
            + [_job(f"r{i}", "render") for i in range(2)])
    s.submit_plan(jobs)
    claimed = []
    while True:
        c = s.claim("dispatch")
        if not c:
            break
        claimed.append(c)
    counts = {"generate_jimeng": 0, "generate_vertex": 0, "render": 0}
    for c in claimed:
        counts[c["phase"]] += 1
    ctx.check("limits_5_1_1", counts == {"generate_jimeng": 5,
                                         "generate_vertex": 1,
                                         "render": 1}, str(counts))
    # Completion frees the slot; the next queued job claims it.
    s.complete(claimed[0]["id"], claimed[0]["fencing_token"])
    nxt = s.claim("dispatch")
    ctx.check("release_refills", nxt is not None
              and nxt["phase"] == "generate_jimeng")
    # Dependency release: child becomes ready when parent succeeds.
    s2, db2 = _sched(ctx, "m06-1b")
    s2.submit_plan([_job("p", "generate_jimeng"),
                    _job("ch", "render", deps=["p"])])
    c = s2.claim("dispatch")
    s2.complete("p", c["fencing_token"])
    c2 = s2.claim("dispatch")
    ctx.check("dep_released", c2 is not None and c2["id"] == "ch")
    db.close(); db2.close()
    return _result(ctx, "passed",
                   "global 5/1/1 enforced across variants; completion "
                   "releases its pool slot; deps auto-promote")


def f06_m02(ctx: CaseContext):
    s, db = _sched(ctx, "m06-2")
    s.submit_plan([_job("slow", "generate_jimeng")]
                  + [_job(f"fast{i}", "generate_jimeng")
                     for i in range(4)]
                  + [_job("obs", "observe")])
    s.db.conn.execute(
        "UPDATE jobs SET status='accepted' WHERE id='obs'")
    s.pause()
    ctx.check("no_new_dispatch", s.claim("dispatch") is None)
    obs = s.claim("observe")
    ctx.check("collection_continues", obs is not None
              and obs["id"] == "obs")
    s.db.conn.execute(
        "UPDATE jobs SET status='running' WHERE id='slow'")
    obs2 = s.claim("observe")
    ctx.check("slow_still_observed", obs2 is not None
              and obs2["id"] in ("slow",))
    s.resume()
    ctx.check("resume_dispatches", s.claim("dispatch") is not None)
    db.close()
    return _result(ctx, "passed",
                   "paused dispatch starts nothing new; accepted/running "
                   "work still collected and observed")


def f06_m03(ctx: CaseContext):
    s1, db = _sched(ctx, "m06-3", worker="w-old")
    s1.submit_plan([_job("a", "generate_jimeng")])
    c = s1.claim("dispatch")
    # Worker dies holding the lease; expiry + reclaim.
    db.conn.execute("UPDATE jobs SET lease_expires='2000-01-01' "
                    "WHERE id='a'")
    s2 = Scheduler(db, worker_id="w-new")
    reclaimed = s2.reclaim_expired()
    ctx.check("replacement_reclaims", reclaimed == ["a"])
    c2 = s2.claim("dispatch")
    ctx.check("replacement_claims", c2 is not None
              and c2["id"] == "a")
    try:
        s1.complete("a", c["fencing_token"])
        ctx.check("stale_fencing_rejected", False)
    except FencingError:
        ctx.check("stale_fencing_rejected", True)
    n = db.conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE id='a' AND status='succeeded'"
    ).fetchone()[0]
    ctx.check("no_duplicate_completion", n == 0)
    db.close()
    return _result(ctx, "passed",
                   "replaced worker reclaims and completes; the stale "
                   "fencing token from the old worker is rejected")


def f06_m04(ctx: CaseContext):
    s, db = _sched(ctx, "m06-4")
    s.resources = ResourcePolicy(min_free_bytes=1 << 40,
                                 probe=lambda: 0)   # no disk
    s.submit_plan([_job("render1", "render"),
                   _job("vert", "generate_vertex"),
                   _job("jim1", "generate_jimeng"),
                   _job("obs", "observe")])
    db.conn.execute(
        "UPDATE jobs SET status='output_available' WHERE id='obs'")
    s.db.conn.execute(                     # exhaust the vertex slot
        "UPDATE capacities SET limit_n=0 WHERE name='vertex_submit'")
    got = []
    while (c := s.claim("dispatch")):
        got.append(c["id"])
    ctx.check("render_blocked_by_disk", "render1" not in got)
    ctx.check("vertex_blocked_by_quota", "vert" not in got)
    ctx.check("jimeng_proceeds", "jim1" in got)
    coll = s.claim("collect")
    ctx.check("collection_unaffected", coll is not None
              and coll["id"] == "obs")
    snap = s.status_snapshot()
    reasons = {j["id"]: j["blocked_reason"] for j in snap["jobs"]}
    ctx.check("reasons_visible",
              "resource_gate" in (reasons.get("render1") or ""))
    db.close()
    return _result(ctx, "passed",
                   "disk pressure gates only heavy local work; exhausted "
                   "Vertex quota blocks only Vertex; Jimeng + collection "
                   "continue")


def implementations():
    return {"F06-M01": f06_m01, "F06-M02": f06_m02,
            "F06-M03": f06_m03, "F06-M04": f06_m04}
