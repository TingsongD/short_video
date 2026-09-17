"""F32 analytics: due windows, supported queries, coverage,
missingness vs zero, OAuth expiry, delayed data, retention>1,
duplicate snapshots, cohorts, manual import, legacy compat."""
import pytest

from modules.factory.analytics.client import (ANALYTICS_PER_VIDEO,
                                              FactoryAnalyticsClient)
from modules.factory.analytics.compat import (legacy_baseline,
                                              legacy_window)
from modules.factory.analytics.service import ReadbackService
from modules.factory.domain.errors import ContractError
from modules.factory.publishing.service import PublishingService
from modules.factory.store import Database
from modules.factory.testing.fakes import FakeAnalytics, FakePublisher

T0 = "2026-09-10T07:00:00+00:00"          # publication time
T48 = "2026-09-12T10:00:00+00:00"         # past 48h due
T7D = "2026-09-17T10:00:00+00:00"         # past 7d due
SHA = "ab" * 32


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _publication(db, pid="pub-1", post="yt-1"):
    from modules.factory.integrations.publisher import UploadPostPublisher
    remote=FakePublisher();remote.plant_post(post,published_at=T0)
    svc = PublishingService(db,publisher=UploadPostPublisher(transport=remote.transport,verifier=remote.verify_post),accounts={"youtube:acct-main":"acct-main"})
    svc.register_manual(
        pid, variant_plan_id="vp-1", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id=post, published_at=T0, verify=True)


def _svc(db, fake=None):
    f = fake or FakeAnalytics()
    client = FactoryAnalyticsClient(yt_api_key="k", oauth_token="tok",
                                    transport=f.transport)
    return ReadbackService(db, client), f


# -------------------------------------------------------- due math --

def test_due_windows_from_actual_publication_time(db):
    _publication(db)
    svc, _ = _svc(db)
    due = {d["horizon"]: d["status"] for d in svc.due("pub-1", now=T48)}
    assert due == {"48h": "due", "7d": "not_due", "28d": "not_due"}
    due7 = {d["horizon"]: d["status"] for d in svc.due("pub-1", now=T7D)}
    assert due7["48h"] == "due" and due7["7d"] == "due"
    assert due7["28d"] == "not_due"


def test_collect_before_due_refused(db):
    _publication(db)
    svc, _ = _svc(db)
    with pytest.raises(ContractError) as e:
        svc.collect("pub-1", "28d", now=T7D)
    assert e.value.code == "horizon_not_due"


# ------------------------------------------------------ wire contract --

def test_queries_hit_supported_routes_only(db):
    _publication(db)
    svc, fake = _svc(db)
    svc.collect("pub-1", "48h", now=T48)
    urls = [r["url"] for r in fake.requests]
    analytics = [u for u in urls if "youtubeanalytics" in u]
    reach = [u for u in urls if "youtubereporting" in u]
    assert len(analytics) == 1 and len(reach) == 3
    assert "impressions" not in analytics[0] and "ctr" not in \
        analytics[0].replace("ClickThrough", "")
    assert reach[0].endswith('/v1/jobs')
    assert '/jobs/job-reach/reports' in reach[1]
    assert '/media/' in reach[2]
    authed = [r for r in fake.requests
              if "analytics" in r["url"] or "reporting" in r["url"]]
    assert all(r["headers"].get("Authorization") for r in authed)


def test_client_refuses_unsupported_metrics():
    c = FactoryAnalyticsClient(transport=lambda r: {"status": 200,
                                                  "body": {}})
    with pytest.raises(ValueError):
        c.analytics_report("yt1", "2026-09-10", "2026-09-12",
                           ["views", "ctr"])
    with pytest.raises(ValueError):
        c.analytics_report("yt1", "2026-09-10", "2026-09-12",
                           ["impressions"])


def test_unsupported_metric_gets_400_from_provider():
    fake = FakeAnalytics()
    c = FactoryAnalyticsClient(oauth_token="t", transport=fake.transport)
    # bypass client validation to prove the fake enforces the wire too
    from urllib.parse import urlencode
    url = ("https://youtubeanalytics.googleapis.com/v2/reports?" +
           urlencode({"ids": "channel==MINE", "metrics": "views,ctr"}))
    resp = fake.transport({"url": url,
                           "headers": {"Authorization": "Bearer t"}})
    assert resp["status"] == 400


# --------------------------------------------------- normalization --

def test_collect_stores_raw_and_normalized(db):
    _publication(db)
    svc, _ = _svc(db)
    snap = svc.collect("pub-1", "48h", now=T48)
    assert snap.metrics["views"] == 2400            # summed day rows
    assert snap.metrics["avg_view_duration_s"] == pytest.approx((18.5*1000+17*1400)/2400)
    assert snap.metrics["thumbnail_impressions"] == 68500
    assert snap.metrics["thumbnail_ctr"] == pytest.approx((38500*6.2+30000*5.8)/68500)
    assert snap.metrics["public_views"] == 2400     # data api
    assert snap.raw["analytics"]["rows"]            # raw preserved
    assert snap.requested_period['start']=='2026-09-10' and snap.requested_period['end']=='2026-09-11'
    assert snap.requested_period['window_kind']=='exact_rolling'


def test_zero_is_zero_missing_is_unknown(db):
    _publication(db)
    fake = FakeAnalytics(
        analytics_rows=[["2026-09-10", 0.0, 0.0, 0, 0, 0, 0]],
        reach_rows=[["2026-09-10", 0, 0.0]],
        stats={"viewCount": "0"})
    svc, _ = _svc(db, fake)
    snap = svc.collect("pub-1", "48h", now=T48)
    assert snap.metrics["views"] == 0
    assert snap.availability["views"] == "ok"       # measured zero
    fake2 = FakeAnalytics(analytics_rows=[], reach_rows=[])
    svc2, _ = _svc(db, fake2)
    snap2 = svc2.collect("pub-1", "7d", now=T7D)
    assert snap2.metrics["views"] is None
    assert snap2.availability["views"] == "no_rows_yet"
    assert snap2.completeness == "pending"


def test_retention_above_one_preserved(db):
    _publication(db)
    fake = FakeAnalytics(analytics_rows=[
        ["2026-09-10", 20.0, 120.0, 4, 9, 3, 500],
        ["2026-09-11", 22.0, 132.0, 4, 9, 3, 500]])
    svc, _ = _svc(db, fake)
    snap = svc.collect("pub-1", "48h", now=T48)
    assert snap.metrics["avg_view_pct"] == 126.0    # never clamped


def test_delayed_retry_updates_same_snapshot(db):
    _publication(db)
    fake = FakeAnalytics(faults={"delayed"})
    svc, _ = _svc(db, fake)
    s1 = svc.collect("pub-1", "48h", now=T48)
    assert s1.completeness == "pending"
    fake.faults.discard("delayed")
    s2 = svc.collect("pub-1", "48h", now="2026-09-13T09:00:00+00:00")
    assert s2.id == s1.id                           # same sample
    assert s2.attempts == 2
    assert s2.completeness == "complete"


def test_partial_route_failure_is_partial(db):
    _publication(db)
    fake = FakeAnalytics(faults={"reach_down"})
    svc, _ = _svc(db, fake)
    snap = svc.collect("pub-1", "48h", now=T48)
    assert snap.completeness == "partial"
    assert snap.availability["thumbnail_ctr"] == "route_failed"
    assert snap.metrics["views"] == 2400            # other route fine


def test_oauth_expiry_marks_failed_routes(db):
    _publication(db)
    fake = FakeAnalytics(faults={"oauth_expired"})
    svc, _ = _svc(db, fake)
    snap = svc.collect("pub-1", "48h", now=T48)
    assert snap.completeness == "partial"           # data api ok
    assert "401" in snap.raw["analytics_error"]


def test_coverage_short_of_horizon_is_partial(db):
    _publication(db)
    fake = FakeAnalytics(analytics_rows=[
        ["2026-09-10", 18.0, 60.0, 4, 9, 3, 900]],
        reach_rows=[["2026-09-10", 20000, 5.0]])
    svc, _ = _svc(db, fake)
    snap = svc.collect("pub-1", "48h", now=T48)
    assert snap.actual_coverage["end"] == "2026-09-10"
    assert snap.completeness == "partial"
    assert snap.missing_reason == "coverage_short_of_horizon"


# -------------------------------------------------------- baseline --

def test_baseline_observed_and_unknown(db):
    svc, _ = _svc(db)
    out = svc.baseline("@ourchannel")
    assert out["median"] == 1500.0 and out["reason"] == "ok"
    fake = FakeAnalytics(channel_doc={"uploads": "", "ids": [],
                                    "views": []})
    svc2, _ = _svc(db, fake)
    out2 = svc2.baseline("@ghost")
    assert out2["median"] is None
    assert out2["reason"] == "channel_not_found"


def test_legacy_baseline_adapter_maps_none_to_zero():
    assert legacy_baseline({"median": None}) == 0.0
    assert legacy_baseline({"median": 1500.0}) == 1500.0


# --------------------------------------------------------- compare --

def test_compare_requires_matched_complete_coverage(db):
    _publication(db, "pub-1", "yt-1")
    _publication(db, "pub-2", "yt-2")
    svc, _ = _svc(db)
    svc.collect("pub-1", "48h", now=T48)
    out = svc.compare(["pub-1", "pub-2"], "48h")
    assert out["comparable"] is False
    assert out["entries"][1]["status"] == "pending"
    svc.collect("pub-2", "48h", now=T48)
    out2 = svc.compare(["pub-1", "pub-2"], "48h")
    assert out2["comparable"] is True
    assert out2["descriptive"] is True


def test_pending_retry_not_a_new_sample(db):
    _publication(db)
    fake = FakeAnalytics(faults={"delayed"})
    svc, _ = _svc(db, fake)
    svc.collect("pub-1", "48h", now=T48)
    svc.collect("pub-1", "48h", now="2026-09-13T00:00:00+00:00")
    rows = db.uow().conn.execute(
        "SELECT COUNT(DISTINCT id) c FROM records WHERE kind='metricsnapshot'"
    ).fetchone()
    assert rows["c"] == 1


# ---------------------------------------------------------- manual --

def test_manual_import_explicit_source_period_confidence(db):
    _publication(db)
    svc, _ = _svc(db)
    snap = svc.import_manual(
        "pub-1", metrics={"views": 500, "saves": 12},
        period={"start": "2026-09-10", "end": "2026-09-17"},
        confidence="medium", source_name="creator-studio-export")
    assert snap.source == "manual:creator-studio-export"
    assert snap.metrics == {"views": 500, "saves": 12}
    assert snap.availability["views"] == "manual"
    with pytest.raises(ContractError):
        svc.import_manual("pub-1", metrics={"views": 1},
                          period={"start": "", "end": ""},
                          confidence="high", source_name="x")
    with pytest.raises(ContractError):
        svc.import_manual("pub-1", metrics={"views": 1},
                          period={"start": "a", "end": "b"},
                          confidence="sure", source_name="x")


def test_manual_import_never_invents_metrics(db):
    _publication(db)
    svc, _ = _svc(db)
    snap = svc.import_manual(
        "pub-1", metrics={"views": 42},
        period={"start": "a", "end": "b"},
        confidence="low", source_name="csv")
    assert "thumbnail_ctr" not in snap.metrics


# ----------------------------------------------------- legacy compat --

def test_legacy_window_adapter(db):
    _publication(db)
    svc, _ = _svc(db)
    snap = svc.collect("pub-1", "48h", now=T48)
    w = legacy_window(snap.__dict__ | snap.metrics and
                      {"metrics": snap.metrics,
                       "observed_at": snap.observed_at,
                       "availability": snap.availability})
    assert w["views"] == 2400 and w["subs_gained"] == 5
    fake = FakeAnalytics(analytics_rows=[], reach_rows=[], stats={})
    svc2, _ = _svc(db, fake)
    snap2 = svc2.collect("pub-1", "7d", now=T7D)
    w2 = legacy_window({"metrics": snap2.metrics,
                        "observed_at": snap2.observed_at,
                        "availability": snap2.availability})
    assert w2["views"] == 0                       # None → 0 (legacy)
    assert w2["availability"]["views"] == "no_rows_yet"
