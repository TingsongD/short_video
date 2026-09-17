"""F32 manual scenarios: fixed-clock horizon progression, query
inspection + missingness truth, OAuth recovery, live-gate shape."""
from .cases_f01 import CaseContext, _result
from ..analytics.client import FactoryAnalyticsClient
from ..analytics.service import ReadbackService
from ..publishing.service import PublishingService
from ..store import Database
from ..testing.fakes import FakeAnalytics

T0 = "2026-09-10T09:00:00+00:00"
SHA = "ab" * 32


def _db(ctx, name):
    return Database(ctx.run_dir / f"{name}.db")


def _svc(db, fake):
    client = FactoryAnalyticsClient(yt_api_key="k", oauth_token="tok",
                                    transport=fake.transport)
    return ReadbackService(db, client)


def _pub(db, pid="pub-1", post="yt-1"):
    PublishingService(
        db, accounts={"youtube:acct-main": "acct-main"}
    ).register_manual(
        pid, variant_plan_id="vp-1", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id=post, published_at=T0, verify=False)


def f32_m01(ctx: CaseContext):
    """Advance the fake clock through 48h/7d/28d — each horizon links
    the correct post/coverage and reports pending accurately."""
    db = _db(ctx, "m01")
    _pub(db)
    svc = _svc(db, FakeAnalytics())
    states = []
    for horizon, now in (("48h", "2026-09-12T10:00:00+00:00"),
                         ("7d", "2026-09-17T10:00:00+00:00"),
                         ("28d", "2026-10-08T10:00:00+00:00")):
        due = {d["horizon"]: d["status"]
               for d in svc.due("pub-1", now=now)}
        snap = svc.collect("pub-1", horizon, now=now)
        states.append((horizon, due[horizon], snap.completeness,
                       snap.post_id, snap.actual_coverage["days"]))
    checks = {
        "each_due_when_time_passes": all(s[1] == "due"
                                         for s in states),
        "correct_post_linked": all(s[3] == "yt-1" for s in states),
        "coverage_recorded": all(s[4] > 0 for s in states),
        "not_due_before_time": svc.due(
            "pub-1", now="2026-09-11T00:00:00+00:00"
        )[0]["status"] == "not_due",
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail={"states": states, "checks": checks})


def f32_m02(ctx: CaseContext):
    """Inspect actual queries; fixtures for no-rows, measured zero,
    unavailable baseline and retention 1.2 — truth is preserved at
    both factory and legacy boundaries."""
    db = _db(ctx, "m02")
    _pub(db)
    fake = FakeAnalytics(analytics_rows=[
        ["2026-09-10", 20.0, 126.0, 4, 9, 3, 800],
        ["2026-09-11", 22.0, 114.0, 4, 9, 3, 700]])
    svc = _svc(db, fake)
    snap = svc.collect("pub-1", "48h", now="2026-09-12T10:00:00+00:00")
    urls = [r["url"] for r in fake.requests]
    zero = FakeAnalytics(analytics_rows=[
        ["2026-09-10", 0.0, 0.0, 0, 0, 0, 0]],
        reach_rows=[["2026-09-10", 0, 0.0]],
        stats={"viewCount": "0"})
    _pub(db, "pub-2", "yt-2")
    svc2 = _svc(db, zero)
    z = svc2.collect("pub-2", "48h", now="2026-09-12T10:00:00+00:00")
    empty = FakeAnalytics(analytics_rows=[], reach_rows=[])
    _pub(db, "pub-3", "yt-3")
    svc3 = _svc(db, empty)
    m = svc3.collect("pub-3", "48h", now="2026-09-12T10:00:00+00:00")
    ghost = _svc(db, FakeAnalytics(
        channel_doc={"uploads": "", "ids": [], "views": []}))
    checks = {
        "reach_uses_reporting_route": any(
            "channel_reach_basic_a1" in u and
            "video_thumbnail_impressions" in u for u in urls),
        "no_generic_ctr_sent": not any(
            "metrics" in u and ",ctr" in u or "ctr," in u
            for u in urls if "youtubeanalytics" in u),
        "zero_stays_zero": z.metrics["views"] == 0
        and z.availability["views"] == "ok",
        "missing_stays_unknown": m.metrics["views"] is None
        and m.completeness == "pending",
        "retention_1_2_preserved": snap.metrics["avg_view_pct"] == 120.0,
        "baseline_unknown_not_zero": ghost.baseline("@x")["median"]
        is None,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f32_m03(ctx: CaseContext):
    """Expire OAuth, delay one variant's coverage; refresh and repeat —
    snapshots preserved, comparison stays pending, retries add no
    samples."""
    db = _db(ctx, "m03")
    _pub(db, "pub-1", "yt-1")
    _pub(db, "pub-2", "yt-2")
    fake = FakeAnalytics(faults={"oauth_expired"})
    svc = _svc(db, fake)
    s1 = svc.collect("pub-1", "48h", now="2026-09-12T10:00:00+00:00")
    fake.faults.discard("oauth_expired")
    fake.faults.add("delayed")
    s2 = svc.collect("pub-1", "48h", now="2026-09-13T10:00:00+00:00")
    fake.faults.discard("delayed")
    s3 = svc.collect("pub-1", "48h", now="2026-09-14T10:00:00+00:00")
    cmp_before = svc.compare(["pub-1", "pub-2"], "48h")
    n_snaps = db.uow().conn.execute(
        "SELECT COUNT(*) c FROM records WHERE kind='metricsnapshot'"
    ).fetchone()["c"]
    checks = {
        "oauth_failed_loudly": s1.completeness == "partial",
        "delayed_is_pending": s2.completeness == "pending",
        "recovery_completes": s3.completeness == "complete",
        "same_snapshot_retries": s1.id == s2.id == s3.id
        and s3.attempts == 3,
        "compare_stays_pending": cmp_before["comparable"] is False,
        "no_extra_samples": n_snaps == 1,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f32_m04(ctx: CaseContext):
    """Live gate: real qualified account report vs dashboard — pending
    until a real due horizon exists."""
    return _result(
        ctx, "awaiting_manual_review",
        "requires a real published post past a due horizon plus a "
        "qualified live account — compare saved query/coverage with "
        "the dashboard when both exist",
        detail={"engineering": "covered by M01–M03"})


def implementations():
    return {"F32-M01": f32_m01, "F32-M02": f32_m02,
            "F32-M03": f32_m03, "F32-M04": f32_m04}
