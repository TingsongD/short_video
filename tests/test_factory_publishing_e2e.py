"""PL-T30: offline end-to-end — four accepted finals, metadata
packages, sixteen mocked destination publications, receipts, 24h
observations, best-of-four seed selection and a Round-2 proposal."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from modules.factory.analytics.client import FactoryAnalyticsClient
from modules.factory.analytics.service import ReadbackService
from modules.factory.api.app import create_app
from modules.factory.bootstrap import bootstrap
from modules.factory.integrations.publisher import UploadPostPublisher
from modules.factory.services.worker import ApplicationWorker
from modules.factory.testing.fakes import FakeAnalytics, FakePublisher
from test_factory_application import DiskDrive
from test_factory_publishing_loop import _publishable

# 2026-09-17T07:00Z is midnight America/Los_Angeles (PDT) — a
# 24h window ending exactly at the next LA midnight is the only
# 'exact_rolling' (complete) case the readback service recognizes.
PUB_AT = "2026-09-17T07:00:00+00:00"
OBS_AT = "2026-09-19T12:00:00+00:00"          # past the 24h checkpoint


@pytest.fixture
def app(tmp_path):
    remote = FakePublisher(users=("acct-main", "tt-1", "ig-1", "fb-1"),
                           now_fn=lambda: PUB_AT)
    remote.default_steps = ["processing", "public"]
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=remote.transport,
                                  verifier=remote.verify_post)
    analytics = FakeAnalytics()
    # Expected coverage days are LA-local: publish at LA midnight
    # 09-17, 24h due at LA midnight 09-18 — window = LA day 09-17.
    analytics.analytics_rows = [["2026-09-17", 18.5, 61.0, 4, 350, 9, 3, 3, 500],
                              ["2026-09-18", 17.0, 58.0, 3, 300, 7, 2, 2, 500]]
    analytics.reach_rows = [["2026-09-17", 38500, 6.2],
                            ["2026-09-18", 30000, 5.8]]
    client = FactoryAnalyticsClient(transport=analytics.transport)
    accounts = {"youtube:acct-main": "acct-main",
                "tiktok:tt-1": "tt-1",
                "instagram:ig-1": "ig-1",
                "facebook:fb-1": "fb-1"}
    service = bootstrap(tmp_path, drive=DiskDrive(tmp_path / "remote"),
                        publisher=adapter, analytics_client=client,
                        settings={"drive_folder_id": "folder",
                                  "raise_worker_errors": True,
                                  "publication_accounts": accounts,
                                  "posts_per_day": 40})
    service.fixture_remote = remote
    service.fixture_analytics = analytics
    # Readback clock sits past the 24h checkpoint for every horizon
    # collected in this journey.
    service.readback = ReadbackService(
        service.db, client,
        clock=lambda: OBS_AT,
        publisher_metrics={"upload_post": adapter.analytics})
    http = TestClient(create_app(service, session_token="test-session"))
    seq = [0]
    def act(method, path, body=None, rev=None, **kw):
        seq[0] += 1
        headers = {"x-csrf-token": "test-session",
                   "idempotency-key": kw.pop("key", f"act-{seq[0]}")}
        if rev is not None:
            headers["x-expected-revision"] = str(rev)
        headers.update(kw.pop("headers", {}))
        return getattr(http, method)(path, json=body, headers=headers,
                                     **kw)
    yield service, http, act, ApplicationWorker(service), tmp_path
    service.db.close()


def _freeze_metadata(app, variant_id, platform):
    s, c, act, w, root = app
    final_sha = s._final(variant_id)[1]["sha256"]
    r = act("post", f"/api/variants/{variant_id}/metadata",
            {"platform": platform, "final_sha256": final_sha,
             "context": {"seed_title": "E2E champion",
                         "hypothesis": "caption lift"},
             "disclosures": {"ai_content": "no",
                             "branded_content": "no",
                             "audience": "general"}},
            rev=1)
    assert r.status_code == 201, r.text
    pkg = r.json()["metadata_package"]
    # CAS handle is the DB row version (1 = just created).
    r = act("put", f"/api/metadata/{pkg['id']}/select",
            {"candidate_id": "c1", "reviewer": "fixture-operator",
             "fields": {"title": "E2E champion", "description": "d",
                        "tags": ""}},
            rev=1)
    assert r.status_code == 200, r.text
    r = act("post", f"/api/metadata/{pkg['id']}/freeze", {}, rev=2)
    assert r.status_code == 200, r.text
    return r.json()


def _publish_all(app):
    s, c, act, w, root = app
    dests = [{"platform": p, "account_id": a}
             for p, a in [("youtube", "acct-main"), ("tiktok", "tt-1"),
                          ("instagram", "ig-1"), ("facebook", "fb-1")]]
    r = act("post", "/api/experiments/fixture-exp/publications",
            {"destinations": dests, "reviewer": "fixture-operator"},
            rev=1)
    assert r.status_code == 201, r.text
    out = r.json()
    assert len(out["publications"]) == 16, out["errors"]
    for p in out["publications"]:
        r = act("post", f"/api/publications/{p['id']}/authorize",
                {"final_sha256": p["final_sha256"],
                 "platform": p["platform"],
                 "account_id": p["account_id"], "action": "publish",
                 "reviewer": "fixture-operator",
                 "valid_until": (datetime.now(timezone.utc) +
                                 timedelta(hours=1)).isoformat()})
        assert r.status_code == 200, r.text
        r = act("post", f"/api/publications/{p['id']}/run", {})
        assert r.status_code == 202, r.text
        deadline = 40
        while deadline and s.publishing.get(p["id"])["status"] != \
                "public":
            out_tick = w.tick()
            if out_tick is None:
                # Deferred observation waits 2s; advance the injected
                # scheduler clock instead of sleeping.
                s.scheduler.clock = (
                    lambda t=s.scheduler.clock() +
                    timedelta(seconds=3): t)
                continue
            # A later horizon claimed against a different clock is
            # deferred observation, not a publication failure.
            if out_tick.get("error") == "horizon_not_due":
                continue
            assert out_tick.get("status") not in ("blocked", "failed"), \
                out_tick
            deadline -= 1
        assert s.publishing.get(p["id"])["status"] == "public", p["id"]
    return out["publications"]


def _plant_metrics(app, pubs):
    s, c, act, w, root = app
    remote, analytics = s.fixture_remote, s.fixture_analytics
    for p in pubs:
        vid = s.detail("variantplan", p["variant_plan_id"]) \
            .get("variant_key", "A")
        views = {"A": 500, "B": 1400, "C": 300, "D": 200}[vid]
        if p["platform"] == "youtube":
            continue                       # native analytics rows below
        remote.plant_metrics(s.publishing.get(p["id"])["remote_post_id"], {
            "views": views, "likes": views // 10,
            "comments": views // 50, "shares": views // 40,
            "saves": views // 60, "reach": views * 3,
            "avg_watch_time_s": 18.0,
            "completion_rate": 61.0})


def _collect_all(app, pubs, horizon="24h"):
    s, c, act, w, root = app
    analytics = s.fixture_analytics
    # Collect at the checkpoint instant — the durable job fires at
    # published_at+horizon; collecting at wall-clock now would record
    # an honestly-late snapshot that no longer represents the age.
    collect_at = (datetime.fromisoformat(PUB_AT) +
                  timedelta(hours=int(horizon.rstrip('h')))).isoformat()
    for p in pubs:
        vid = s.detail("variantplan", p["variant_plan_id"]) \
            .get("variant_key", "A")
        views = {"A": 500, "B": 1400, "C": 300, "D": 200}[vid]
        if p["platform"] == "youtube":
            for row in analytics.analytics_rows:
                row[-1] = views
            for row in analytics.reach_rows:
                row[-2] = views * 30
        # A checkpoint job may already have collected during the publish
        # loop (real wall clock is past the due instant); its snapshot
        # carries the readback clock's OBS_AT. The deliberate collect
        # must observe no earlier, or ranking prefers the stale one.
        # Source-calendar windows tolerate a late observation — the
        # source days it covers are fixed regardless.
        observe_at = collect_at if p["platform"] != "youtube" else \
            (datetime.fromisoformat(OBS_AT) +
             timedelta(seconds=1)).isoformat()
        snap = s.checkpoints.collect(p["id"], horizon, now=observe_at)
        assert snap.completeness == "complete", (
            p["platform"], snap.availability)


def test_readback_not_due_on_observation_clock_defers(app):
    """A scheduler clock past 72h must not fail the job when the
    readback clock is still before that horizon."""
    s, c, act, w, root = app
    s.fixture_remote.plant_post("yt-deferred", published_at=PUB_AT)
    s.publishing.register_manual(
        "pub-deferred", variant_plan_id="vp-1",
        final_sha256="ab" * 32, platform="youtube",
        account_id="acct-main", remote_post_id="yt-deferred",
        published_at=PUB_AT, verify=True)
    s.checkpoints.schedule_for(s.publishing.get("pub-deferred"))
    s.scheduler.clock = lambda: datetime.fromisoformat(
        "2026-09-21T00:00:00+00:00")
    seen = None
    for _ in range(20):
        out = w.tick()
        if out is None:
            break
        if out.get("error") == "horizon_not_due":
            seen = out
            break
    assert seen is not None, "72h readback was never claimed"
    assert seen.get("status") == "pending"
    job = s.db.uow().jobs.get(seen["job_id"])
    assert job["status"] != "failed"
    assert job.get("next_attempt_at")


def test_full_publish_learn_next_round_journey(app):
    s, c, act, w, root = app
    sp = {"mode": "weighted_rank",
          "weights": {"youtube": 0.4, "tiktok": 0.3,
                      "instagram": 0.15, "facebook": 0.15},
          "provisional_horizon": "24h",
          "improvement_rule": {"kind": "weighted_lift"}}
    variants = _publishable(app, policy_extra={
        "primary_metric": "views", "min_exposure": 0,
        "practical_lift": 0.2, "seed_policy": sp})
    # Freeze metadata for B/youtube — auto-attached at batch planning.
    b = next(v for v in s.experiment_results("fixture-exp")["variants"]
             if v["variant_key"] == "B")
    _freeze_metadata(app, b["id"], "youtube")

    pubs = _publish_all(app)
    # Receipts: every slot carries native identity + actual pub time.
    for p in pubs:
        got = s.publishing.get(p["id"])
        assert got["remote_post_id"], got
        assert got["published_at"] == PUB_AT
        assert got["provider"] == "upload_post"
    by_vp = {p["variant_plan_id"]: p for p in pubs
             if p["platform"] == "youtube"}
    assert s.publishing.get(by_vp[b["id"]]["id"]) \
        ["metadata_package_id"].startswith("mp-")

    # Auto-scheduled checkpoints on the public transition — elapsed
    # horizons plus the complete-day windows YouTube's source-calendar
    # route qualifies for (§8.2).
    cps = s.checkpoints.for_publication(pubs[0]["id"])
    assert {x["horizon"] for x in cps} == {
        "24h", "48h", "72h", "7d", "28d",
        "7d_complete", "28d_complete"}

    _plant_metrics(app, pubs)
    _collect_all(app, pubs)

    # Per-platform decisions: B beat A on every lane.
    for platform in ("youtube", "tiktok", "instagram", "facebook"):
        dec = s.learning.decide("fixture-exp", 1, platform=platform)
        assert dec["conclusion"] == "provisional_winner", (
            platform, dec["conclusion"])
        assert dec["winner"] == "B"

    # Best-of-four seed selection — champion B, provisional.
    sel = s.learning.select_seed("fixture-exp", 1, horizon="24h")
    assert sel["outcome"] == "champion"
    assert sel["winner_variant"] == "B"
    assert sel["status"] == "provisional"

    # Bounded Round-2 proposal — derived seed + lineage. The series id
    # is series:{seed_id} of the experiment's seed.
    er = s.db.uow().records.get("experimentrevision", "exp:fixture-exp")
    seed_id = json.loads(er["body"])["seed_id"]
    r = act("post", f"/api/series/series:{seed_id}/loop",
            {"reviewer": "fixture-operator", "mode": "propose_only",
             "max_rounds": 2})
    assert r.status_code == 201, r.text
    r = act("post", "/api/experiments/fixture-exp/rounds",
            {"selection_id": sel["id"]}, rev=1)
    assert r.status_code == 201, r.text
    out = r.json()
    child = out["seed"]
    assert child["parent_seed_id"]
    assert child["round"] == 1
    assert child["independence_group"]
    lin = out["lineage"]
    assert lin["status"] == "proposed"
    assert lin["parent_selection_id"] == sel["id"]
    # A second proposal from the same selection is idempotent.
    r2 = act("post", "/api/experiments/fixture-exp/rounds",
             {"selection_id": sel["id"]}, rev=1)
    assert r2.status_code == 201, r2.text
    assert r2.json()["idempotent"] is True
