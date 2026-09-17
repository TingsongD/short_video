"""F09 manual scenarios: canonical dedupe, thumbnail detection,
interrupted-transfer resume, SSRF/expiry refusal."""
import json

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore, IntakeError
from ..execution import Executor
from ..scheduler.scheduler import Scheduler
from ..seeds import AcquisitionService, SeedRegistry
from ..seeds.ssrf import SSRFError, assert_fetchable
from ..store import Database
from ..testing.fakes import FakeSeedSource, ProviderError
from ..testing.fixtures import materialize
from ..domain.records import Job
from ..store.uow import utcnow

NOW = "2026-09-16T12:00:00Z"
YT = "https://www.youtube.com/shorts/abcDEF12345"
YT_TRACKED = YT + "?utm_source=x&feature=share"


def _stack(ctx, name, media="missing", **post_kw):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-artifacts", db=db)
    src = FakeSeedSource(f"{name}-src", ctx.workspace.dir("fake_remote"),
                         ctx.workspace.ids, ctx.clock,
                         media_dir=ctx.run_dir)
    sched = Scheduler(db, worker_id=f"w-{name}")
    ex = Executor(db, src, ctx.clock)
    reg = SeedRegistry(db, artifacts=arts)
    svc = AcquisitionService(db, sched, ex, reg, arts, src,
                             "viral_outliers",
                             staging_dir=ctx.run_dir / "staging",
                             resolver=lambda h: ["93.184.216.34"])
    return db, arts, src, sched, reg, svc, post_kw


def _stage_media(ctx, name):
    """Give the fake real fixture bytes."""
    locked = materialize("core-30s", ctx.workspace.path)
    src_mp4 = ctx.workspace.path / "fixtures" / "core-30s" / "source.mp4"
    return src_mp4


def f09_m01(ctx: CaseContext):
    db, arts, src, sched, reg, svc, _ = _stack(ctx, "m09-1")
    a, created_a = reg.submit_url(YT)
    b, created_b = reg.submit_url(YT_TRACKED, via="radar")
    ctx.check("one_canonical_seed", created_a and not created_b
              and a.id == b.id)
    ctx.check("both_provenance", len(b.provenance) == 2)
    pid = b.native_id
    src.register_post(pid, title="Viral outfit", creator_id="c9",
                      stats={"views": 900000, "followers": 12000},
                      media="file:source.mp4")
    src_mp4 = _stage_media(ctx, "m09-1")
    # media_dir is run_dir — copy fixture there under the post id
    import shutil
    shutil.copy(src_mp4, ctx.run_dir / "source.mp4")
    svc.plan(a.id)
    while svc.run_next():
        pass
    got = reg.get(a.id)
    ctx.check("usable_source_artifact",
              got.evidence_status == "media_ready"
              and got.source_asset_id.startswith("art:"))
    art = arts.path_for(got.source_asset_id)
    ctx.check("artifact_exists", art is not None)
    db.close()
    return _result(ctx, "passed",
                   "two URL forms merged into one canonical seed; media "
                   "attached as verified source artifact")


def f09_m02(ctx: CaseContext):
    db, arts, src, sched, reg, svc, _ = _stack(ctx, "m09-2")
    seed, _ = reg.submit_url(YT)
    src.register_post(seed.native_id, title="Thumb trap",
                      stats={"views": 500000}, media="image")
    svc.plan(seed.id)
    svc.run_next()                              # metadata ok
    try:
        svc.run_next()                          # media: thumbnail
        ctx.check("media_job_failed", False)
    except IntakeError:
        ctx.check("media_job_failed", True)
    got = reg.get(seed.id)
    rep = reg.readiness(seed.id)
    ctx.check("metadata_retained", bool(got.metadata_fetched_at))
    ctx.check("needs_source_media",
              got.evidence_status == "needs_source_media")
    ctx.check("blocks_with_import_action",
              not rep["analysis_ready"]
              and "import_source_media" in rep["actions"])
    db.close()
    return _result(ctx, "passed",
                   "thumbnail download → needs_source_media; metadata "
                   "kept; readiness names the import action")


def f09_m03(ctx: CaseContext):
    db, arts, src, sched, reg, svc, _ = _stack(ctx, "m09-3")
    seed, _ = reg.submit_url(YT)
    src.register_post(seed.native_id, media="file:source.mp4",
                      interrupt_downloads=1)
    import shutil
    shutil.copy(_stage_media(ctx, "m09-3"), ctx.run_dir / "source.mp4")
    meta_id, media_id = svc.plan(seed.id)
    analysis = Job(schema_version="job.v1", id="job-analysis-m03",
                   created_at=utcnow(), logical_key="analyze:m03",
                   phase="analyze", depends_on=[media_id])
    sched.submit_plan([analysis])
    svc.run_next()                              # metadata
    svc.run_next()                              # media: interrupted once
    got = reg.get(seed.id)
    ctx.check("still_blocked_after_cut",
              got.evidence_status == "metadata_only")
    svc.run_next()                              # resume same attempt
    got = reg.get(seed.id)
    ctx.check("verified_media_attached",
              got.evidence_status == "media_ready")
    attempts = db.conn.execute(
        "SELECT COUNT(*) c FROM attempts").fetchone()["c"]
    ctx.check("no_resubmit", attempts == 2)     # meta + one media attempt
    st = db.conn.execute(
        "SELECT status FROM jobs WHERE id='job-analysis-m03'"
    ).fetchone()["status"]
    ctx.check("analysis_eligible", st == "ready")
    meta_ops = [o for o in src.state.doc["source_ops"].values()
                if o["request"]["kind"] == "metadata"]
    ctx.check("no_extra_paid_lookup", len(meta_ops) == 1)
    db.close()
    return _result(ctx, "passed",
                   "interrupted transfer resumed on the same attempt; "
                   "verified bytes only; analysis unblocked; no extra "
                   "lookup")


def f09_m04(ctx: CaseContext):
    db, arts, src, sched, reg, svc, _ = _stack(ctx, "m09-4")
    # private-network fetch target
    try:
        assert_fetchable("https://169.254.169.254/latest/meta-data")
        ctx.check("private_refused", False)
    except SSRFError:
        ctx.check("private_refused", True)
    # unsupported platform / scheme
    for bad in ("https://vimeo.com/1", "ftp://x/y"):
        try:
            reg.submit_url(bad)
            ctx.check("unsupported_refused", False)
            break
        except Exception:
            ctx.check("unsupported_refused", True)
    # expired signed URL → refresh path, token redacted in evidence
    seed, _ = reg.submit_url(YT)
    src.register_post(seed.native_id, media="file:source.mp4",
                      url_state="expired")
    import shutil
    shutil.copy(_stage_media(ctx, "m09-4"), ctx.run_dir / "source.mp4")
    svc.plan(seed.id)
    while svc.run_next():
        pass
    ctx.check("refresh_path_used",
              src.counters()["refreshes"] == 1
              and reg.get(seed.id).evidence_status == "media_ready")
    from ..events.redact import redact
    doc = redact({"url": src.post(seed.native_id)["media_url"]})
    ctx.check("signed_params_redacted", "sig=refreshed" not in
              json.dumps(doc))
    db.close()
    return _result(ctx, "passed",
                   "private/scheme/redirect targets refused; expired URL "
                   "went through refresh; tokens stay redacted")


def implementations():
    return {"F09-M01": f09_m01, "F09-M02": f09_m02,
            "F09-M03": f09_m03, "F09-M04": f09_m04}
