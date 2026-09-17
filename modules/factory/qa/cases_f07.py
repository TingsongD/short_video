"""F07 manual scenarios: crash recovery, resume-by-ID, download retry,
cancel/fallback suppression."""
from .cases_f01 import CaseContext, _result
from ..domain import ContractError
from ..execution import Executor
from ..store import Database
from ..testing.fakes import ProviderError


def _env(ctx, name):
    db = Database(ctx.workspace.dir("store") / f"{name}.db")
    p = ctx.provider(name)
    return db, p, Executor(db, p)


def f07_m01(ctx: CaseContext):
    db, p, ex = _env(ctx, "m07-1")
    aid = ex.prepare("job1", 1, {"prompt": "lost-ack"},
                     provider="fake")
    try:
        ex.submit(aid, call=lambda: p.submit(
            {"prompt": "lost-ack"}, faults=("accept-then-timeout",)))
    except ProviderError:
        pass
    db.close()
    # Restart: fresh executor + fresh provider object, same state files.
    db2 = Database(ctx.workspace.dir("store") / "m07-1.db")
    p2 = ctx.provider("m07-1")
    ex2 = Executor(db2, p2)
    report = ex2.recover()
    ctx.check("one_remote_effect",
              p2.effect_counts()["submit"] == 1)
    ctx.check("reconciled", aid in report["reconciled"])
    row = ex2._attempt(aid)
    ctx.check("remote_id_recovered", bool(row["remote_id"]))
    db2.close()
    return _result(ctx, "passed",
                   "crash after remote acceptance: restart reconciles the "
                   "single remote effect by request hash — no resubmission")


def f07_m02(ctx: CaseContext):
    db, p, ex = _env(ctx, "m07-2")
    aid = ex.prepare("job1", 1, {"prompt": "poll-resume"},
                     provider="fake")
    ex.submit(aid, call=lambda: p.submit({"prompt": "poll-resume"}))
    remote_id = ex._attempt(aid)["remote_id"]
    # Interrupt polling twice; both resumes hit the SAME remote id.
    ex.poll(aid)
    ex.poll(aid)
    op = p.operation(remote_id)
    ctx.check("same_id_polled", op["polls"] == 2)
    ctx.check("submit_once", p.effect_counts()["submit"] == 1)
    db.close()
    return _result(ctx, "passed",
                   "both resumes poll the original operation ID; no new "
                   "generation created")


def f07_m03(ctx: CaseContext):
    db, p, ex = _env(ctx, "m07-3")
    aid = ex.prepare("job1", 1, {"prompt": "dl"},
                     provider="fake")
    ex.submit(aid, call=lambda: p.submit({"prompt": "dl"}))
    ex.poll(aid)
    # Inject download failure on the accepted op, then clear it.
    op = p.state.doc["operations"][ex._attempt(aid)["remote_id"]]
    op["faults"].append("download-failure")
    p.state.save()
    try:
        ex.download(aid)
        ctx.check("first_download_failed", False)
    except ProviderError:
        ctx.check("first_download_failed", True)
    op["faults"].remove("download-failure")
    p.state.save()
    dest = ctx.run_dir / "collected.bin"
    out = ex.download(aid, destination=dest)
    ctx.check("verified_bytes",
              out["sha256"] == op["result"]["content_sha256"])
    counts = p.effect_counts()
    ctx.check("submit_once_download_twice",
              counts["submit"] == 1 and counts["download"] == 2)
    db.close()
    return _result(ctx, "passed",
                   "failed download retries the transfer only — submit "
                   "count stays 1; final bytes hash-verified")


def f07_m04(ctx: CaseContext):
    db, p, ex = _env(ctx, "m07-4")
    aid = ex.prepare("job1", 1, {"prompt": "cancel-race"},
                     provider="fake")
    ex.submit(aid, call=lambda: p.submit({"prompt": "cancel-race"}))
    ex.request_cancel(aid)
    ctx.check("fallback_suppressed", not ex.fallback_allowed(aid))
    ex.poll(aid)      # terminal cancellation observed
    ctx.check("terminal_cancel_seen",
              ex._attempt(aid)["status"] == "cancelled")
    ctx.check("fallback_now_allowed", ex.fallback_allowed(aid))
    try:
        ex.resolve_unknown(aid, "", "confirmed_charged")
        ctx.check("resolution_needs_evidence", False)
    except ContractError:
        ctx.check("resolution_needs_evidence", True)
    db.close()
    return _result(ctx, "passed",
                   "fallback suppressed while cancel unresolved; terminal "
                   "evidence frees it; human resolution requires evidence")


def implementations():
    return {"F07-M01": f07_m01, "F07-M02": f07_m02,
            "F07-M03": f07_m03, "F07-M04": f07_m04}
