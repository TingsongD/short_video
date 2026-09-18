"""PL-05/PL-32..34: platform-aware decide(), best-of-four select_seed
with fixed evaluation order, eligibility, ties, unsafe control and
selection revisions."""
import json

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import (
    ExperimentRevision, MetricSnapshot, Seed, VariantPlan)
from modules.factory.learning.service import LearningService
from modules.factory.store import Database

NOW = "2026-09-17T12:00:00+00:00"
SHA = "ab" * 32


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _experiment(db, eid="exp-1", seed="seed-1", rev=1):
    with db.uow() as u:
        u.records.put(ExperimentRevision(
            schema_version="experiment_revision.v1",
            id=f"exp:{eid}", created_at=NOW, experiment_id=eid,
            revision=rev, status="accepted", seed_id=seed,
            template_ref="fmt-1", content_hash=f"h-{eid}-{rev}"))
        for vk in "ABCD":
            u.records.put(VariantPlan(
                schema_version="variant_plan.v1",
                id=f"vp-{eid}-{vk.lower()}", created_at=NOW,
                experiment_id=eid, experiment_revision=rev,
                variant_key=vk,
                hypothesis="" if vk == "A" else "h",
                changed_factor="" if vk == "A" else "hook",
                status="planned"))


def _pub(db, pid, vp, platform, post, rev=1):
    from modules.factory.domain.records import Publication
    with db.uow() as u:
        u.records.put(Publication(
            schema_version="publication.v1", id=pid, created_at=NOW,
            variant_plan_id=vp, final_sha256=SHA, platform=platform,
            account_id=f"{platform}-acct", remote_post_id=post,
            post_url=f"https://{platform}.example/{post}",
            status="public", provider="upload_post",
            published_at="2026-09-10T09:00:00+00:00",
            experiment_revision=rev))


def _snap(db, pid, horizon, metrics, platform="youtube", hours=48,
          rev=0):
    kind = ("exact_rolling" if platform == "youtube"
            else "observed_lifetime_at_age")
    snap = MetricSnapshot(
        schema_version="metric_snapshot.v1",
        id=f"snap-{pid}-{horizon}", created_at=NOW, revision=rev,
        publication_id=pid, post_id=pid, horizon=horizon,
        query_version="f32.v2",
        requested_period={"horizon_hours": hours, "window_kind": kind},
        source="verified fixture",
        metrics=dict(metrics),
        availability={k: "ok" for k in metrics},
        completeness="complete", observed_at=NOW)
    with db.uow() as u:
        u.records.put(snap)


def _policy(svc, eid="exp-1", rev=1, seed_policy=None, **kw):
    args = dict(policy_version="p1", primary_metric="views",
                horizon="48h", min_exposure=0, practical_lift=0.3,
                exposure_metric="views", seed_policy=seed_policy)
    args.update(kw)
    return svc.freeze_policy(eid, rev, **args)


def _lanes(db, eid, platforms, views, horizon="48h"):
    """One public post + complete snapshot per (variant, platform).
    views: {variant: {platform: value}}"""
    for vk, per in views.items():
        for platform in platforms:
            pid = f"pub-{eid}-{vk.lower()}-{platform}"
            _pub(db, pid, f"vp-{eid}-{vk.lower()}", platform,
                 f"{platform}-{vk}")
            val = per.get(platform)
            if val is None:
                continue
            _snap(db, pid, horizon, {"views": val}, platform)


W2 = {"mode": "weighted_rank",
      "weights": {"youtube": 0.5, "tiktok": 0.5},
      "provisional_horizon": "48h",
      "improvement_rule": {"kind": "weighted_lift"}}


# ---------------------------------------------------- decide() ----

def test_decide_platform_scoped_id_and_lane(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 500, "tiktok": 400},
            "B": {"youtube": 800, "tiktok": 700},
            "C": {"youtube": 300, "tiktok": 300},
            "D": {"youtube": 200, "tiktok": 100}})
    dec = svc.decide("exp-1", 1, platform="tiktok")
    assert dec["id"] == "dec-exp-1-r1-48h-tiktok"
    assert dec["platform"] == "tiktok"
    assert dec["conclusion"] == "provisional_winner"
    assert dec["winner"] == "B"


# ------------------------------------------------- select_seed ----

def test_select_seed_waits_on_missing_required_platform(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2)
    _lanes(db, "exp-1", ["youtube"],
           {"A": {"youtube": 500}, "B": {"youtube": 800},
            "C": {"youtube": 300}, "D": {"youtube": 200}})
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "waiting"
    assert out["status"] == "waiting"
    assert out["basis"]["missing"] == ["tiktok"]


def test_select_seed_a_is_a_legal_winner(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 900, "tiktok": 900},
            "B": {"youtube": 800, "tiktok": 700},
            "C": {"youtube": 300, "tiktok": 300},
            "D": {"youtube": 200, "tiktok": 100}})
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "retain_control"
    assert out["winner_variant"] == "A"
    assert out["status"] == "provisional"


def test_disqualified_top_scorer_falls_back_to_runner_up(db):
    """§9.3 case 1: B ranks first but fails the instagram guardrail —
    C is next eligible and passes → C wins."""
    _experiment(db)
    svc = LearningService(db)
    sp = dict(W2)
    sp["weights"] = {"youtube": 0.5, "instagram": 0.5}
    _policy(svc, seed_policy=sp,
            guardrails={"avg_view_pct": 40})
    _lanes(db, "exp-1", ["youtube", "instagram"],
           {"A": {"youtube": 500, "instagram": 500},
            "B": {"youtube": 900, "instagram": 900},
            "C": {"youtube": 800, "instagram": 700},
            "D": {"youtube": 200, "instagram": 100}})
    # B's instagram guardrail failure (avg_view_pct < 40):
    snap = db.uow().records.get(
        "metricsnapshot", "snap-pub-exp-1-b-instagram-48h")
    body = json.loads(snap["body"])
    body["metrics"]["avg_view_pct"] = 10.0
    body["availability"]["avg_view_pct"] = "ok"
    for vk in "ACD":
        s2 = db.uow().records.get(
            "metricsnapshot",
            f"snap-pub-exp-1-{vk.lower()}-instagram-48h")
        b2 = json.loads(s2["body"])
        b2["metrics"]["avg_view_pct"] = 60.0
        b2["availability"]["avg_view_pct"] = "ok"
        with db.uow() as u:
            u.conn.execute("UPDATE records SET body=? WHERE id=?",
                           (json.dumps(b2), s2["id"]))
    with db.uow() as u:
        u.conn.execute("UPDATE records SET body=? WHERE id=?",
                       (json.dumps(body), snap["id"]))
    # youtube guardrails all pass:
    for vk in "ABCD":
        s3 = db.uow().records.get(
            "metricsnapshot",
            f"snap-pub-exp-1-{vk.lower()}-youtube-48h")
        b3 = json.loads(s3["body"])
        b3["metrics"]["avg_view_pct"] = 60.0
        b3["availability"]["avg_view_pct"] = "ok"
        with db.uow() as u:
            u.conn.execute("UPDATE records SET body=? WHERE id=?",
                           (json.dumps(b3), s3["id"]))
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "champion"
    assert out["winner_variant"] == "C"
    assert "B" in out["basis"]["disqualified"]


def test_min_platforms_rule_counts_named_lanes(db):
    """§9.3 case 2: B beats A on 2 lanes, ties instagram, loses
    facebook; min_platforms=2 → B passes."""
    _experiment(db)
    svc = LearningService(db)
    sp = {"mode": "weighted_rank",
          "weights": {"youtube": 0.34, "tiktok": 0.33,
                      "instagram": 0.17, "facebook": 0.16},
          "provisional_horizon": "48h",
          "improvement_rule": {"kind": "min_platforms",
                               "min_platforms": 2}}
    _policy(svc, seed_policy=sp, practical_lift=0.3)
    _lanes(db, "exp-1",
           ["youtube", "tiktok", "instagram", "facebook"],
           {"A": {"youtube": 500, "tiktok": 500, "instagram": 500,
                  "facebook": 500},
            "B": {"youtube": 700, "tiktok": 700, "instagram": 500,
                  "facebook": 400},
            "C": {"youtube": 300, "tiktok": 300, "instagram": 300,
                  "facebook": 300},
            "D": {"youtube": 200, "tiktok": 200, "instagram": 200,
                  "facebook": 200}})
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "champion"
    assert out["winner_variant"] == "B"
    assert set(out["basis"]["evaluated"]["B"]["beaten"]) == {
        "youtube", "tiktok"}


def test_unsafe_control_makes_evaluation_inconclusive(db):
    """§9.3 case 3: A fails a guardrail on tiktok → invalid
    comparison → inconclusive, never a silent retain."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2, guardrails={"avg_view_pct": 40})
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 500, "tiktok": 500},
            "B": {"youtube": 900, "tiktok": 900},
            "C": {"youtube": 300, "tiktok": 300},
            "D": {"youtube": 200, "tiktok": 100}})
    snap = db.uow().records.get(
        "metricsnapshot", "snap-pub-exp-1-a-tiktok-48h")
    body = json.loads(snap["body"])
    body["metrics"]["avg_view_pct"] = 5.0
    body["availability"]["avg_view_pct"] = "ok"
    with db.uow() as u:
        u.conn.execute("UPDATE records SET body=? WHERE id=?",
                       (json.dumps(body), snap["id"]))
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "inconclusive"
    assert "tiktok" in out["basis"]["invalid_comparison"]


def test_zero_exposure_control_is_not_infinite_lift(db):
    """§9.3 case 5: A views=0 → invalid comparison, never infinity."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 0, "tiktok": 0},
            "B": {"youtube": 900, "tiktok": 900},
            "C": {"youtube": 300, "tiktok": 300},
            "D": {"youtube": 200, "tiktok": 100}})
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "inconclusive"


def test_equal_aggregate_scores_tie_out(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 500, "tiktok": 500},
            "B": {"youtube": 900, "tiktok": 500},
            "C": {"youtube": 500, "tiktok": 900},
            "D": {"youtube": 200, "tiktok": 100}})
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "inconclusive"
    assert set(out["basis"]["tie"]) == {"B", "C"}


def test_no_clearer_retains_eligible_control(db):
    """§9.3 case 4: C ranks first but fails improvement; A eligible
    → retain A."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2, practical_lift=0.9)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 500, "tiktok": 500},
            "B": {"youtube": 300, "tiktok": 300},
            "C": {"youtube": 600, "tiktok": 600},
            "D": {"youtube": 200, "tiktok": 100}})
    out = svc.select_seed("exp-1", 1, horizon="48h")
    assert out["outcome"] == "retain_control"
    assert out["winner_variant"] == "A"


def test_selection_idempotent_then_revised_on_new_evidence(db):
    """Identical inputs → same record; revised evidence → new
    -v{N} revision, prior superseded (PL-T33)."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy=W2)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 500, "tiktok": 500},
            "B": {"youtube": 900, "tiktok": 900},
            "C": {"youtube": 300, "tiktok": 300},
            "D": {"youtube": 200, "tiktok": 100}})
    first = svc.select_seed("exp-1", 1, horizon="48h")
    again = svc.select_seed("exp-1", 1, horizon="48h")
    assert again["id"] == first["id"]
    assert again["_idempotent"] is True
    # Revised evidence: a new snapshot revision flips the winner.
    _snap(db, "pub-exp-1-c-youtube", "48h", {"views": 2000},
          "youtube", rev=1)
    _snap(db, "pub-exp-1-c-tiktok", "48h", {"views": 2000},
          "tiktok", rev=1)
    revised = svc.select_seed("exp-1", 1, horizon="48h")
    assert revised["id"] == first["id"] + "-v1"
    assert revised["winner_variant"] == "C"


def test_independence_group_counts_lineage_once(db):
    """Two experiments from derived seeds in one independence group
    count as ONE independent confirmation (PL-01)."""
    _experiment(db, eid="exp-1", seed="seed-1")
    _experiment(db, eid="exp-2", seed="seed-2")
    with db.uow() as u:
        u.records.put(Seed(schema_version="seed.v1", id="seed-1",
                           created_at=NOW, original_url="u1",
                           independence_group="root-1"))
        u.records.put(Seed(schema_version="seed.v1", id="seed-2",
                           created_at=NOW, original_url="u2",
                           parent_seed_id="seed-1",
                           lineage_root_id="root-1",
                           independence_group="root-1", round=2))
    svc = LearningService(db)
    for eid in ("exp-1", "exp-2"):
        _policy(svc, eid=eid)
        _lanes(db, eid, ["youtube"],
               {"A": {"youtube": 500}, "B": {"youtube": 900},
                "C": {"youtube": 300}, "D": {"youtube": 200}})
        svc.decide(eid, 1)
    seeds = svc.independent_experiments("fmt-1")
    assert seeds == {"root-1"}


def test_select_seed_requires_policy(db):
    _experiment(db)
    svc = LearningService(db)
    with pytest.raises(ContractError) as e:
        svc.select_seed("exp-1", 1)
    assert e.value.code == "policy_not_frozen"
