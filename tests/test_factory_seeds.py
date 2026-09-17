from modules.factory.testing.authority import FixtureEffects
"""F09 — seed registry and source acquisition."""
import json

import pytest

from modules.factory.artifacts.registry import ArtifactStore, IntakeError
from modules.factory.budget.service import BudgetService
from modules.factory.domain.errors import ContractError
from modules.factory.events.redact import redact
from modules.factory.execution.executor import Executor
from modules.factory.integrations.viral_outliers import ViralOutliersSource
from modules.factory.scheduler.scheduler import Scheduler
from modules.factory.seeds import (AcquisitionService, SeedRegistry,
                                   assert_fetchable, parse_source_url)
from modules.factory.seeds.ssrf import SSRFError
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeSeedSource, ProviderError
from modules.factory.testing.fixtures import materialize
from modules.factory.testing.ids import IdFactory

YT = "https://www.youtube.com/shorts/abcDEF12345"
YT_TRACKED = ("https://www.youtube.com/shorts/abcDEF12345"
              "?utm_source=x&feature=share")


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    ids = IdFactory(tmp_path / "ids.json")
    clock = FakeClock()
    ws = tmp_path / "ws"
    locked = materialize("core-30s", ws)
    media_dir = ws / "fixtures" / "core-30s"
    arts = ArtifactStore(tmp_path / "artifacts", db=db)
    src = FakeSeedSource("vo", tmp_path / "remote", ids, clock,
                         media_dir=media_dir)
    sched = Scheduler(db, worker_id="w-test", clock=clock.now)
    ex = Executor(db, src, clock)
    reg = SeedRegistry(db, artifacts=arts)
    svc = AcquisitionService(db, sched, ex, reg, arts, src,
                             "viral_outliers",
                             staging_dir=tmp_path / "staging",
                             resolver=lambda h: ["93.184.216.34"])
    return {"db": db, "ids": ids, "clock": clock, "src": src,
            "sched": sched, "ex": ex, "reg": reg, "svc": svc,
            "arts": arts, "media_dir": media_dir, "tmp": tmp_path}


def _seed(env, url=YT, **kw):
    seed, created = env["reg"].submit_url(url)
    pid = seed.native_id
    env["src"].register_post(pid, **kw)
    return seed


def _run_all(env, n=10):
    ran = []
    for _ in range(n):
        j = env["svc"].run_next()
        if j is None:
            break
        ran.append(j)
    return ran


class TestUrls:
    def test_canonical_forms_dedupe(self, env):
        a, created_a = env["reg"].submit_url(YT)
        b, created_b = env["reg"].submit_url(YT_TRACKED, via="radar")
        assert created_a and not created_b
        assert a.id == b.id
        assert a.id.startswith("seed-youtube-")
        assert len(b.provenance) == 2
        assert {p["via"] for p in b.provenance} == {"manual_url", "radar"}

    def test_tracking_does_not_split_posts(self, env):
        env["reg"].submit_url(YT)
        env["reg"].submit_url(
            "https://youtube.com/shorts/abcDEF12345?si=zzz")
        rows = env["db"].conn.execute(
            "SELECT DISTINCT id FROM records WHERE kind='seed'").fetchall()
        assert len(rows) == 1

    def test_distinct_posts_not_conflated(self, env):
        env["reg"].submit_url(YT)
        env["reg"].submit_url("https://youtu.be/zyxWVUT9876")
        rows = env["db"].conn.execute(
            "SELECT DISTINCT id FROM records WHERE kind='seed'").fetchall()
        assert len(rows) == 2

    def test_unsupported_and_malformed(self, env):
        for bad in ("https://vimeo.com/123", "notaurl",
                    "https://www.tiktok.com/@u/notavideo",
                    "ftp://youtube.com/shorts/abcDEF12345"):
            with pytest.raises(ContractError):
                parse_source_url(bad)

    def test_tiktok_and_instagram(self):
        t = parse_source_url("https://www.tiktok.com/@User.Name/video/1234567890?lang=en")
        assert t["platform"] == "tiktok"
        assert t["canonical_url"].endswith("/video/1234567890")
        i = parse_source_url("https://www.instagram.com/reel/CxYz123/?igsh=zz")
        assert i["platform"] == "instagram"
        assert i["native_id"] == "CxYz123"


class TestSSRF:
    def test_private_ips_refused(self):
        for url in ("https://169.254.169.254/latest/meta-data",
                    "https://127.0.0.1/x", "https://10.0.0.4/x",
                    "https://[::1]/x"):
            with pytest.raises(SSRFError):
                assert_fetchable(url)

    def test_scheme_and_creds_refused(self):
        for url in ("http://example.com/x",
                    "https://user:pw@example.com/x",
                    "https://example.com:8080/x"):
            with pytest.raises(SSRFError):
                assert_fetchable(url)

    def test_private_dns_answer_refused(self):
        with pytest.raises(SSRFError):
            assert_fetchable("https://evil.example.com/x",
                             resolver=lambda h: ["169.254.169.254"])
        assert_fetchable("https://cdn.example.com/x",
                         resolver=lambda h: ["93.184.216.34"])

    def test_adapter_redirect_to_private_refused(self, tmp_path):
        def transport(method, url, body):
            if "content/" in url:
                return 200, {}, json.dumps({"media_url": "https://ok/x"})
            if url == "https://ok/x":
                return 302, {"location": "http://169.254.169.254/m"}, b""
            return 404, {}, b""
        src = ViralOutliersSource(
            transport, tmp_path / "receipts", resolver=lambda h: ["93.184.216.34"])
        with pytest.raises(SSRFError):
            src.submit({"kind": "media", "url": "https://ok/x"})

    def test_adapter_redirect_chain_bounded(self, tmp_path):
        calls = []

        def transport(method, url, body):
            calls.append(url)
            n = len(calls)
            return 302, {"location": f"https://ok/{n}"}, b""
        src = ViralOutliersSource(
            transport, tmp_path / "receipts", resolver=lambda h: ["93.184.216.34"])
        with pytest.raises(SSRFError):       # exceeds redirect limit
            src.submit({"kind": "media", "url": "https://ok/0"})


class TestAcquisition:
    def test_metadata_then_media(self, env):
        seed = _seed(env, title="Outfit math", creator_id="c1",
                     stats={"views": 1000000, "followers": 10000},
                     media="file:source.mp4")
        env["svc"].plan(seed.id)
        _run_all(env)
        got = env["reg"].get(seed.id)
        assert got.evidence_status == "media_ready"
        assert got.title == "Outfit math"
        assert got.metadata_fetched_at
        assert got.source_asset_id.startswith("art:")
        obs = env["db"].conn.execute(
            "SELECT body FROM records WHERE kind='metricobservation'"
        ).fetchall()
        assert json.loads(obs[0]["body"])["views"] == 1000000

    def test_unavailable_post(self, env):
        seed, _ = env["reg"].submit_url(YT)     # never registered remote
        env["svc"].plan(seed.id)
        with pytest.raises(ProviderError):
            _run_all(env)
        job = env["db"].conn.execute(
            "SELECT status FROM jobs WHERE logical_key LIKE 'seed_meta%'"
        ).fetchone()
        assert job["status"] == "failed"

    def test_thumbnail_returns_needs_source_media(self, env):
        seed = _seed(env, media="image")
        env["svc"].plan(seed.id)
        with pytest.raises(IntakeError):
            _run_all(env)
        got = env["reg"].get(seed.id)
        assert got.evidence_status == "needs_source_media"
        assert got.metadata_fetched_at          # metadata survives
        rep = env["reg"].readiness(seed.id)
        assert not rep["analysis_ready"]
        assert "import_source_media" in rep["actions"]

    def test_interrupted_transfer_resumes_same_attempt(self, env):
        seed = _seed(env, media="file:source.mp4", interrupt_downloads=1)
        env["svc"].plan(seed.id)
        env["svc"].run_next()                   # metadata
        env["svc"].run_next()                   # media: download interrupted
        attempts = env["db"].conn.execute(
            "SELECT * FROM attempts ORDER BY attempt_seq").fetchall()
        assert len(attempts) == 2               # meta + one media attempt
        assert env["svc"].run_next() is None    # respects bounded backoff
        env["clock"].advance(seconds=3)
        env["svc"].run_next()                   # resumes SAME attempt
        got = env["reg"].get(seed.id)
        assert got.evidence_status == "media_ready"
        attempts = env["db"].conn.execute(
            "SELECT * FROM attempts ORDER BY attempt_seq").fetchall()
        assert len(attempts) == 2               # no resubmit
        assert env["src"].counters()["download"] == 2

    def test_expired_url_refresh_path(self, env):
        seed = _seed(env, media="file:source.mp4", url_state="expired")
        env["svc"].plan(seed.id)
        _run_all(env)
        assert env["reg"].get(seed.id).evidence_status == "media_ready"
        assert env["src"].counters()["refreshes"] == 1
        # refreshed URL persisted on the seed
        assert "refreshed" in env["reg"].get(seed.id).metadata["media_url"]

    def test_private_media_url_refused_before_call(self, env):
        seed = _seed(env, media="file:source.mp4",
                     media_url="https://169.254.169.254/latest/meta-data")
        env["svc"].plan(seed.id)
        env["svc"].run_next()                   # metadata ok
        with pytest.raises(SSRFError):
            env["svc"].run_next()               # media refused pre-submit
        assert env["src"].counters()["submit"] == 1   # only metadata call

    def test_metadata_cache_avoids_second_lookup(self, env):
        seed = _seed(env, media="file:source.mp4",
                     stats={"views": 5})
        env["svc"].plan(seed.id)
        _run_all(env)                           # full base acquisition
        # re-resolution pass inside TTL → cache hit, no new lookup
        meta_id, _ = env["svc"].plan(seed.id, suffix=":r2")
        env["svc"].run_next()
        evs = env["db"].conn.execute(
            "SELECT type FROM events WHERE stream=?",
            (f"job:{meta_id}",)).fetchall()
        assert any(e["type"] == "cache_hit" for e in evs)
        meta_ops = [o for o in
                    env["src"].state.doc["source_ops"].values()
                    if o["request"]["kind"] == "metadata"]
        assert len(meta_ops) == 1


class TestManualImport:
    def test_manual_import_resumes_blocked_analysis(self, env):
        seed = _seed(env, media="image")
        meta_id, media_id = env["svc"].plan(seed.id)
        # downstream analysis depends on the media job
        from modules.factory.domain.records import Job
        from modules.factory.store.uow import utcnow
        analysis = Job(schema_version="job.v1", id="job-analysis-1",
                       created_at=utcnow(), logical_key="analyze:s1",
                       phase="analyze", depends_on=[media_id])
        env["sched"].submit_plan([analysis])
        with pytest.raises(IntakeError):
            _run_all(env)
        blocked = env["db"].conn.execute(
            "SELECT status FROM jobs WHERE id='job-analysis-1'"
        ).fetchone()["status"]
        assert blocked == "blocked"
        src = env["media_dir"] / "source.mp4"
        env["reg"].import_manual(seed.id, src)
        got = env["reg"].get(seed.id)
        assert got.evidence_status == "media_ready"
        st = env["db"].conn.execute(
            "SELECT status FROM jobs WHERE id='job-analysis-1'"
        ).fetchone()["status"]
        assert st == "ready"

    def test_manual_import_rejects_nonvideo(self, env):
        seed, _ = env["reg"].submit_url(YT)
        ws_png = env["media_dir"] / "product-1.png"
        with pytest.raises(IntakeError):
            env["reg"].import_manual(seed.id, ws_png)
        assert env["reg"].get(seed.id).evidence_status == "metadata_only"


class TestReadiness:
    def test_metadata_only_not_ready(self, env):
        seed = _seed(env)
        rep = env["reg"].readiness(seed.id)
        assert rep["status"] == "metadata_only"
        assert not rep["analysis_ready"]

    def test_provenance_survives_media_refresh(self, env):
        seed = _seed(env, media="file:source.mp4", url_state="expired")
        env["reg"].submit_url(YT_TRACKED, via="radar")
        env["svc"].plan(seed.id)
        _run_all(env)
        got = env["reg"].get(seed.id)
        assert len(got.provenance) == 2
        assert got.evidence_status == "media_ready"


class TestBudget:
    def test_paid_lookup_reserves_and_settles(self, env):
        budget = BudgetService(env["db"])
        budget.create_budget("b-research", "viral_outliers_credits", "provider",
                             scope_key="viral_outliers", cap=10)
        env["svc"].budget = budget
        env["svc"].effects = FixtureEffects(env["db"], env["ex"])
        env["svc"].costs = {"metadata": {"lines": [("b-research", 1)]}}
        seed = _seed(env, media="missing", stats={"views": 7})
        env["svc"].plan(seed.id)
        env["svc"].run_next()
        rows = env["db"].conn.execute(
            "SELECT status FROM reservations").fetchall()
        assert rows[0]["status"] == "settled"
        assert env["src"].counters()["submit"] == 1

    def test_unclassified_failed_lookup_retains_reservation(self, env):
        budget = BudgetService(env["db"])
        budget.create_budget("b-research", "viral_outliers_credits", "provider",
                             scope_key="viral_outliers", cap=10)
        env["svc"].budget = budget
        env["svc"].effects = FixtureEffects(env["db"], env["ex"])
        env["svc"].costs = {"metadata": {"lines": [("b-research", 1)]}}
        seed, _ = env["reg"].submit_url(YT)     # post not registered
        env["svc"].plan(seed.id)
        with pytest.raises(ProviderError):
            env["svc"].run_next()
        rows = env["db"].conn.execute(
            "SELECT status FROM reservations").fetchall()
        assert rows[0]["status"] == "ambiguous"
