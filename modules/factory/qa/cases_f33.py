"""F33 manual scenarios: reproducible decision, defined no-winner
handling, sibling counting, and independent-seed promotion."""
import json

from .cases_f01 import CaseContext, _result
from ..domain.errors import ContractError
from ..domain.records import (ExperimentRevision, MetricSnapshot,
                              VariantPlan)
from ..learning.service import LearningService
from ..publishing.service import PublishingService
from ..store import Database

NOW = "2026-09-17T12:00:00+00:00"
SHA = "ab" * 32


def _db(ctx, name):
    return Database(ctx.run_dir / f"{name}.db")


def _experiment(db, eid="exp-1", seed="seed-1", template="fmt-1"):
    with db.uow() as u:
        u.records.put(ExperimentRevision(
            schema_version="experiment_revision.v1", id=f"{eid}-r1",
            created_at=NOW, experiment_id=eid, revision=1,
            status="accepted", seed_id=seed, template_ref=template,
            content_hash=f"h-{eid}"))
        for vk in "ABCD":
            u.records.put(VariantPlan(
                schema_version="variant_plan.v1",
                id=f"vp-{eid}-{vk.lower()}", created_at=NOW,
                experiment_id=eid, experiment_revision=1,
                variant_key=vk,
                hypothesis="" if vk == "A" else "h",
                changed_factor="" if vk == "A" else "hook",
                status="planned"))


def _rich(v):
    return {"views": v, "thumbnail_impressions": 5000,
            "avg_view_pct": 70.0}


def _publish(db, eid, vals):
    pub_svc = PublishingService(
        db, accounts={"youtube:acct-main": "acct-main"})
    for vk, metrics in vals.items():
        pid = f"pub-{eid}-{vk.lower()}"
        pub_svc.register_manual(
            pid, variant_plan_id=f"vp-{eid}-{vk.lower()}",
            final_sha256=SHA, platform="youtube",
            account_id="acct-main", remote_post_id=f"yt-{pid}",
            published_at="2026-09-10T09:00:00+00:00", verify=False)
        if metrics is None:
            continue
        with db.uow() as u:
            u.records.put(MetricSnapshot(
                schema_version="metric_snapshot.v1",
                id=f"snap-{pid}-48h", created_at=NOW,
                publication_id=pid, post_id=f"yt-{pid}",
                horizon="48h", query_version="f32.v1",
                metrics=metrics,
                availability={k: "ok" for k in metrics},
                completeness="complete", observed_at=NOW))


def _policy(svc, eid="exp-1", **kw):
    args = dict(policy_version="p1", primary_metric="views",
                horizon="48h", practical_lift=0.3)
    args.update(kw)
    return svc.freeze_policy(eid, 1, **args)


def f33_m01(ctx: CaseContext):
    """Evaluate the fixed complete fixture and recompute — identical
    decision and explanation."""
    db = _db(ctx, "m01")
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(900), "d": _rich(800)})
    d1 = svc.decide("exp-1", 1)
    d2 = svc.decide("exp-1", 1)
    s1, s2 = svc.summary(d1["id"]), svc.summary(d1["id"])
    checks = {
        "same_decision": d2.get("_idempotent") is True
        and d1["conclusion"] == "provisional_winner",
        "same_explanation": s1 == s2 and "B" in s1,
        "reproducible_inputs": bool(d1["inputs_hash"]),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f33_m02(ctx: CaseContext):
    """Missing horizon data, zero control and low exposure each get
    defined handling — never an automatic winner."""
    db = _db(ctx, "m02")
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, min_exposure=50000)
    _publish(db, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(900), "d": _rich(800)})
    low = svc.decide("exp-1", 1)
    db2 = _db(ctx, "m02b")
    _experiment(db2)
    svc2 = LearningService(db2)
    _policy(svc2)
    _publish(db2, "exp-1", {"a": _rich(0), "b": _rich(1400),
                            "c": _rich(900), "d": _rich(800)})
    zero = svc2.decide("exp-1", 1)
    db3 = _db(ctx, "m02c")
    _experiment(db3)
    svc3 = LearningService(db3)
    _policy(svc3)
    _publish(db3, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                            "c": _rich(900), "d": None})
    miss = svc3.decide("exp-1", 1)
    checks = {
        "low_exposure": low["conclusion"] == "insufficient_exposure",
        "zero_baseline_defined": zero["conclusion"] == "inconclusive"
        and any("zero_baseline" in l for l in zero["limitations"]),
        "missing_is_pending": miss["conclusion"] ==
        "waiting_for_data",
        "no_automatic_winner": not any(
            d["conclusion"] == "provisional_winner"
            for d in (low, zero, miss)),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f33_m03(ctx: CaseContext):
    """Re-reading the same four posts stays one experiment — sibling
    variants cannot manufacture independent confirmations."""
    db = _db(ctx, "m03")
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(1350), "d": _rich(1300)})
    for _ in range(3):
        svc.decide("exp-1", 1)
    out = svc.promote("fmt-1", min_independent=2)
    checks = {
        "one_experiment": out["independent_experiments"] == 1,
        "not_proven": out["status"] == "promising",
        "limitation_stated": "sibling" in out["limitation"],
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f33_m04(ctx: CaseContext):
    """A second independent seed + a revised policy keep lineage
    distinct; promotion follows the declared rule with limitations."""
    db = _db(ctx, "m04")
    svc = LearningService(db)
    for eid, seed in (("exp-1", "seed-1"), ("exp-2", "seed-2")):
        _experiment(db, eid, seed=seed)
        _policy(svc, eid=eid,
                policy_version="p1" if eid == "exp-1" else "p2")
        _publish(db, eid, {"a": _rich(1000), "b": _rich(1400),
                           "c": _rich(900), "d": _rich(800)})
        svc.decide(eid, 1)
    out = svc.promote("fmt-1", min_independent=2)
    policies = [json.loads(r["body"])["policy_version"]
                for r in db.uow().conn.execute(
                    "SELECT body FROM records "
                    "WHERE kind='decisionpolicy' ORDER BY id")]
    decisions = db.uow().conn.execute(
        "SELECT id FROM records WHERE kind='decision'").fetchall()
    checks = {
        "two_independent": out["independent_experiments"] == 2,
        "proven_per_rule": out["status"] == "proven",
        "policy_lineage": policies == ["p1", "p2"],
        "decisions_distinct": len(decisions) == 2,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def implementations():
    return {"F33-M01": f33_m01, "F33-M02": f33_m02,
            "F33-M03": f33_m03, "F33-M04": f33_m04}
