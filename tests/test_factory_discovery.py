from modules.factory.testing.authority import FixtureEffects
"""F10 — outlier discovery and baseline evidence."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.factory.discovery import (DiscoveryService, baseline_multiple,
                                       build_cohort, evaluate,
                                       follower_multiple, passes)
from modules.factory.discovery.evaluate import MODES
from modules.factory.domain.errors import ContractError
from modules.factory.execution.executor import Executor
from modules.factory.seeds import SeedRegistry
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeDiscovery, ProviderError
from modules.factory.testing.ids import IdFactory
from modules.radar.viral_records import normalize

FIX = Path("tests/factory_fixtures")
NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)

CRITERIA = {"breakout_subs_ratio": 2, "max_video_age_days": 30,
            "cluster_min_channels": 2, "platforms": ["youtube"]}


def _fx(name):
    return json.loads((FIX / name / f"{name.split('-')[-1]}.json"
                       ).read_text()) if False else None


def load_fixture_dir(name):
    d = FIX / name
    return {p.stem: json.loads(p.read_text()) for p in d.glob("*.json")}


class TestCohortMath:
    def test_outlier_math_fixture(self):
        fx = load_fixture_dir("outlier-math")["cohort"]
        seed, cohort_videos = fx["seed"], fx["cohort"]["videos"]
        # Exclusions listed in the fixture must all be excluded by rule.
        all_pool = cohort_videos + [
            {"post_id": e["post_id"],
             "published_at": e.get("published_at"),
             "format": e.get("format", "haul"),
             "platform": "youtube", "views": 20000}
            for e in fx["cohort"]["excluded"]]
        cohort = build_cohort(seed, all_pool)
        assert cohort["size"] == 20
        assert cohort["mean_views"] == 20000
        assert cohort["median_views"] == 20000
        assert seed["post_id"] not in cohort["included"]
        excluded_ids = {e["post_id"] for e in cohort["excluded"]}
        assert seed["post_id"] in excluded_ids
        assert "yt-x-01" in excluded_ids      # published after seed
        assert "yt-x-02" in excluded_ids      # mixed format
        # 1,000,000 / 10,000 = 100x followers; 1,000,000 / 20,000 = 50x
        assert follower_multiple(seed["views"], seed["followers"]) == 100.0
        assert baseline_multiple(seed["views"],
                                 cohort["median_views"]) == 50.0

    def test_follower_strict_boundaries(self):
        fx = load_fixture_dir("outlier-boundaries")["boundaries"]
        followers = fx["followers"]
        for case in fx["views_cases"]:
            fm = follower_multiple(case["views"], followers)
            got = fm is not None and fm > 2
            assert got == case["expect_follower_pass"], case["note"]

    def test_baseline_inclusive_threshold(self):
        fx = load_fixture_dir("outlier-boundaries")["boundaries"]
        for case in fx["baseline_cases"]:
            got = passes("baseline", None, case["baseline_multiple"],
                         baseline_threshold=5.0)
            assert got == case["expect_baseline_pass"], case.get("note")

    def test_sample_size_confidence(self):
        fx = load_fixture_dir("outlier-boundaries")["boundaries"]
        for case in fx["sample_size_cases"]:
            cohort = {"size": case["cohort_size"],
                      "median_views": 20000,
                      "flags": (["small_sample"]
                                if case["cohort_size"] < 20 else [])}
            r = evaluate({"post_id": "x", "views": 100000,
                          "followers": 10000}, cohort, mode="either")
            assert r["confidence"] == case["expect_confidence"]


class TestNullHandling:
    def test_hidden_counts_are_null_not_infinite(self):
        assert follower_multiple(50000, None) is None
        assert follower_multiple(50000, 0) is None
        assert baseline_multiple(50000, None) is None
        assert baseline_multiple(50000, 0) is None
        r = evaluate({"post_id": "x", "views": 50000, "followers": None},
                     {"size": 25, "median_views": 10000, "flags": []},
                     mode="both")
        assert r["follower_multiple"] is None
        assert r["baseline_multiple"] == 5.0
        assert not r["selected"]            # both: missing follower fails
        assert "followers_unavailable" in r["reasons"]

    def test_zero_views_not_outlier(self):
        r = evaluate({"post_id": "x", "views": 0, "followers": 10000},
                     {"size": 20, "median_views": 100, "flags": []},
                     mode="either")
        assert r["follower_multiple"] == 0.0
        assert not r["selected"]


class TestModes:
    """All four modes through the ACTIVE Viral Outliers normalize path —
    contrasting denominators prove no hidden follower-only gate."""

    def _row(self, views):
        return {"id": "p1", "platform": "youtube", "views": views,
                "followerCount": 10000, "title": "t",
                "publishedAt": "2026-09-15T00:00:00Z",
                "contentType": "shorts",
                "postLink": "https://www.youtube.com/shorts/abcDEF12345",
                "profile": {"channel_id": "UC1", "handle": "@c"}}

    def test_modes_contrast(self):
        # views/followers = 3 (passes strict >2); baseline 1.5 (fails >=5)
        for mode, expected in (("follower", True), ("baseline", False),
                               ("either", True), ("both", False)):
            crit = dict(CRITERIA, selection_mode=mode,
                        baseline_threshold=5.0, cohort_median_views=20000)
            _, obs = normalize(self._row(30000), NOW, crit)
            assert obs["ratio_pass"] is expected, mode
            assert obs["selection_mode"] == mode

    def test_baseline_only_selection(self):
        # views/followers = 1.5 (fails >2); baseline 7.5 (passes >=5)
        for mode, expected in (("follower", False), ("baseline", True),
                               ("either", True), ("both", False)):
            crit = dict(CRITERIA, selection_mode=mode,
                        baseline_threshold=5.0, cohort_median_views=2000)
            video, obs = normalize(self._row(15000), NOW, crit)
            assert obs["ratio_pass"] is expected, mode
            if expected:
                assert video["baseline_available"] is True
                assert video["channel_avg"] == 2000.0
                assert video["multiplier"] == 7.5

    def test_default_mode_unchanged(self):
        """Legacy default stays follower-only — regression guard."""
        _, obs = normalize(self._row(20001), NOW, dict(CRITERIA))
        assert obs["ratio_pass"] is True
        _, obs = normalize(self._row(20000), NOW, dict(CRITERIA))
        assert obs["ratio_pass"] is False
        assert obs["selection_mode"] == "follower"

    def test_plan_persists_modes(self, tmp_path):
        from modules.radar import viral_scan
        niche = [{"name": "n", "keywords": ["haul"]}]
        for mode in MODES:
            plan = viral_scan.prepare(
                tmp_path / f"r-{mode}", f"run-{mode}", niche,
                dict(CRITERIA, selection_mode=mode,
                     baseline_threshold=5.0, cohort_median_views=20000),
                platforms=["youtube"])
            loaded = viral_scan.load_plan(tmp_path / f"r-{mode}",
                                          f"run-{mode}")
            assert loaded["criteria"]["selection_mode"] == mode
            assert loaded["criteria"]["cohort_median_views"] == 20000

    def test_plan_rejects_bad_mode(self, tmp_path):
        from modules.radar import viral_scan
        from modules.radar.viral_client import ViralError
        with pytest.raises(ViralError):
            viral_scan.prepare(tmp_path / "r", "run-x",
                               [{"name": "n", "keywords": ["k"]}],
                               dict(CRITERIA, selection_mode="bogus"),
                               platforms=["youtube"])


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    ids = IdFactory(tmp_path / "ids.json")
    clock = FakeClock()
    src = FakeDiscovery("vo-disc", tmp_path / "remote", ids, clock)
    ex = Executor(db, src, clock)
    reg = SeedRegistry(db)
    svc = DiscoveryService(db, reg, ex, src, effects=FixtureEffects(db, ex))
    return {"db": db, "src": src, "svc": svc, "reg": reg}


def _post(pid, views, followers=10000, day="2026-09-10", fmt="haul",
          url=None):
    return {"post_id": pid, "platform": "youtube", "views": views,
            "followers": followers, "published_at": day + "T00:00:00Z",
            "format": fmt, "title": f"t-{pid}",
            "source_url": url or
            f"https://www.youtube.com/shorts/{pid[:11].ljust(11, 'x')}",
            "provider_score": 9.1}


class TestService:
    def test_rank_and_export(self, env):
        seed_post = _post("yt-seed-0001", 1000000)
        cohort = [_post(f"yt-c-{i:02d}", 20000,
                        day=f"2026-08-{10 + i:02d}") for i in range(20)]
        env["src"].set_credits(5)
        env["src"].set_results("haul", 1, [seed_post] + cohort)
        run = env["svc"].scan(["haul"], pages=1, page_size=50,
                              mode="both", run_id="drun-r1")
        assert run.status == "complete"
        top = run.candidates[0]
        assert top["post_id"] == "yt-seed-0001"
        assert top["follower_multiple"] == 100.0
        assert top["baseline_multiple"] == 50.0
        assert top["provider_score"] == 9.1       # kept distinct
        assert top["selected"]
        assert run.exported_seed_ids             # exported to registry
        assert env["reg"].get(run.exported_seed_ids[0]).native_id

    def test_partial_coverage_on_credit_exhaustion(self, env):
        posts = [_post(f"yt-p{p}", 30000) for p in range(3)]
        env["src"].set_credits(1)                # only ONE page affordable
        env["src"].set_results("haul", 1, posts)
        env["src"].set_results("haul", 2, posts)
        run = env["svc"].scan(["haul"], pages=2, run_id="drun-r2")
        assert run.status == "partial"
        assert run.coverage["received_pages"] == 1
        assert "insufficient_credits" in run.coverage["partial_reason"]
        # No top-up: provider balance stays 0; no duplicate charges
        assert env["src"].counters()["charges"] == 1
        assert env["src"].credits() == 0

    def test_restart_uses_cache_no_duplicate_charge(self, env):
        env["src"].set_credits(1)
        env["src"].set_results("haul", 1, [_post("a1", 30000)])
        env["src"].set_results("haul", 2, [_post("a2", 30000)])
        env["svc"].scan(["haul"], pages=2, run_id="drun-r3")
        # Restart: new service + executor, same db and provider state.
        src2 = FakeDiscovery("vo-disc", env["db"].path and
                             Path(env["db"].path).parent / "remote",
                             IdFactory(Path(env["db"].path).parent /
                                       "ids.json"), FakeClock())
        ex2 = Executor(env["db"], src2, FakeClock())
        svc2 = DiscoveryService(env["db"], env["reg"], ex2, src2, effects=FixtureEffects(env["db"], ex2))
        run2 = svc2.scan(["haul"], pages=2, run_id="drun-r4")
        assert src2.counters()["charges"] == 1   # page 1 from cache
        assert run2.status == "partial"          # still no credits

    def test_manual_seed_intake_unaffected(self, env):
        env["src"].set_credits(0)
        run = env["svc"].scan(["haul"], pages=1, run_id="drun-r5")
        assert run.status == "partial"
        seed, created = env["reg"].submit_url(
            "https://www.youtube.com/shorts/zzzZZZ999yy", via="manual")
        assert created and seed.id

    def test_small_sample_flagged(self, env):
        seed = _post("s1", 100000, day="2026-09-10")
        cohort = [_post(f"c{i}", 20000,
                        day=f"2026-08-{i + 1:02d}") for i in range(5)]
        env["src"].set_credits(5)
        env["src"].set_results("q", 1, [seed] + cohort)
        run = env["svc"].scan(["q"], pages=1, run_id="drun-r6",
                              mode="either")
        cand = next(c for c in run.candidates if c["post_id"] == "s1")
        assert "small_sample" in cand["reasons"]
        assert cand["confidence"] == "low"
