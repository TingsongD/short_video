"""F10 manual scenarios: cohort math evidence, boundary modes, null
handling, credit-exhausted pagination."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .cases_f01 import CaseContext, _result
from ..discovery import build_cohort, evaluate, follower_multiple
from ..discovery.service import DiscoveryService
from ..execution import Executor
from ..seeds import SeedRegistry
from ..store import Database
from ..testing.fakes import FakeDiscovery
from ..testing.ids import IdFactory
from modules.radar.viral_records import normalize
from modules.radar import viral_scan

FIX = Path("tests/factory_fixtures")
NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)
CRITERIA = {"breakout_subs_ratio": 2, "max_video_age_days": 30,
            "cluster_min_channels": 2, "platforms": ["youtube"]}


def _stack(ctx, name, credits=0):
    db = Database(ctx.run_dir / f"{name}.db")
    src = FakeDiscovery(f"{name}-disc", ctx.workspace.dir("fake_remote"),
                        ctx.workspace.ids, ctx.clock, credits=credits)
    ex = Executor(db, src, ctx.clock)
    reg = SeedRegistry(db)
    svc = DiscoveryService(db, reg, ex, src)
    return db, src, reg, svc


def f10_m01(ctx: CaseContext):
    fx = json.loads((FIX / "outlier-math" / "cohort.json").read_text())
    seed = fx["seed"]
    pool = fx["cohort"]["videos"] + [
        {"post_id": e["post_id"], "published_at": e.get("published_at"),
         "format": e.get("format", "haul"), "platform": "youtube",
         "views": 20000}
        for e in fx["cohort"]["excluded"]]
    cohort = build_cohort(seed, pool)
    ctx.check("cohort_20", cohort["size"] == 20)
    ctx.check("mean_median_20k", cohort["mean_views"] == 20000
              and cohort["median_views"] == 20000)
    ctx.check("seed_excluded", seed["post_id"] in
              {e["post_id"] for e in cohort["excluded"]})
    ctx.check("future_excluded", "yt-x-01" in
              {e["post_id"] for e in cohort["excluded"]})
    ctx.check("mixed_format_excluded", "yt-x-02" in
              {e["post_id"] for e in cohort["excluded"]})
    fm = follower_multiple(seed["views"], seed["followers"])
    bm = seed["views"] / cohort["median_views"]
    ctx.check("math_100x_50x", fm == 100.0 and bm == 50.0)
    return _result(ctx, "passed",
                   "1M/10k = 100× followers; mean & median baseline = "
                   "50×; seed excluded from its own cohort")


def f10_m02(ctx: CaseContext):
    fx = json.loads(
        (FIX / "outlier-boundaries" / "boundaries.json").read_text())
    ok = True
    for case in fx["views_cases"]:
        row = {"id": "b", "platform": "youtube", "views": case["views"],
               "followerCount": fx["followers"], "title": "t",
               "publishedAt": "2026-09-15T00:00:00Z",
               "contentType": "shorts",
               "postLink": "https://www.youtube.com/shorts/abcDEF12345",
               "profile": {"channel_id": "UC1"}}
        _, obs = normalize(row, NOW, dict(CRITERIA,
                                        selection_mode="follower"))
        ok = ok and obs["ratio_pass"] == case["expect_follower_pass"]
    ctx.check("strict_boundaries", ok)   # only 20,001 passes
    # All four modes through persisted saved plans, contrasting
    # denominators: fm=3 (pass) / bm=1.5 (fail).
    expected = {"follower": True, "baseline": False,
                "either": True, "both": False}
    for mode, want in expected.items():
        root = ctx.run_dir / f"plans-{mode}"
        plan = viral_scan.prepare(
            root, f"run-{mode}", [{"name": "n", "keywords": ["haul"]}],
            dict(CRITERIA, selection_mode=mode, baseline_threshold=5.0,
                 cohort_median_views=20000), platforms=["youtube"])
        loaded = viral_scan.load_plan(root, f"run-{mode}")
        row = {"id": "m", "platform": "youtube", "views": 30000,
               "followerCount": 10000, "title": "t",
               "publishedAt": "2026-09-15T00:00:00Z",
               "contentType": "shorts",
               "postLink": "https://www.youtube.com/shorts/abcDEF12345",
               "profile": {"channel_id": "UC1"}}
        _, obs = normalize(row, NOW, loaded["criteria"])
        ctx.check(f"mode_{mode}",
                  obs["ratio_pass"] is want
                  and loaded["criteria"]["selection_mode"] == mode)
    return _result(ctx, "passed",
                   "only 20,001 passes strict >2; every persisted mode "
                   "applies its declared denominators")


def f10_m03(ctx: CaseContext):
    # followers removed, cohort shrunk, stale/mixed observations
    seed = {"post_id": "s1", "platform": "youtube", "views": 80000,
            "followers": None, "published_at": "2026-09-10T00:00:00Z",
            "format": "haul"}
    pool = ([{"post_id": f"c{i}", "platform": "youtube",
              "views": 20000, "published_at": f"2026-08-{i+1:02d}T00:00:00Z",
              "format": "haul"} for i in range(5)]
            + [{"post_id": "old", "platform": "youtube", "views": 20000,
                "published_at": "2026-05-01T00:00:00Z", "format": "haul"}])
    cohort = build_cohort(seed, pool)
    ctx.check("small_sample_flag", "small_sample" in cohort["flags"])
    ctx.check("mixed_periods_flag", "mixed_periods" in cohort["flags"])
    r = evaluate(seed, cohort, mode="both")
    ctx.check("null_not_infinite", r["follower_multiple"] is None
              and r["baseline_multiple"] is not None)
    ctx.check("unselected_explained", not r["selected"]
              and "followers_unavailable" in r["reasons"]
              and r["confidence"] == "low")
    return _result(ctx, "passed",
                   "missing ratios stay null; small/stale cohorts flagged; "
                   "strong-looking numbers explain their disqualification")


def f10_m04(ctx: CaseContext):
    db, src, reg, svc = _stack(ctx, "m10-4", credits=1)
    posts = [{"post_id": f"p{p}", "platform": "youtube", "views": 30000,
              "followers": 9000,
              "published_at": "2026-09-05T00:00:00Z", "format": "haul",
              "title": "t",
              "source_url":
              f"https://www.youtube.com/shorts/{'x' * (11 - len(str(p)))}{p}"}
             for p in range(3)]
    src.set_results("haul", 1, posts)
    src.set_results("haul", 2, posts)
    run = svc.scan(["haul"], pages=2, run_id="drun-m04")
    ctx.check("partial_recorded", run.status == "partial"
              and run.coverage["received_pages"] == 1)
    ctx.check("no_topup", src.credits() == 0
              and src.counters()["charges"] == 1)
    # restart: cached page not re-charged
    svc2 = DiscoveryService(db, reg,
                            Executor(db, src, ctx.clock), src)
    run2 = svc2.scan(["haul"], pages=2, run_id="drun-m04b")
    ctx.check("cache_no_recharge",
              src.counters()["charges"] == 1
              and run2.status == "partial")
    # manual seed intake still works
    seed, created = reg.submit_url(
        "https://www.youtube.com/shorts/zzzZZZ999yy", via="manual")
    ctx.check("manual_intake_works", created)
    db.close()
    return _result(ctx, "passed",
                   "credit exhaustion → explicit partial coverage; restart "
                   "uses cache without re-charging; manual intake works")


def implementations():
    return {"F10-M01": f10_m01, "F10-M02": f10_m02,
            "F10-M03": f10_m03, "F10-M04": f10_m04}
