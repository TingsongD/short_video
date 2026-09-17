"""F33 learning: frozen policy, deterministic decisions, exposure/
zero-baseline handling, guardrails, multiplicity, idempotent
recompute, revisioned decisions, independent-seed counting,
hypotheses and non-causal summaries."""
import json

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import (ExperimentRevision,
                                            MetricSnapshot,
                                            VariantPlan)
from modules.factory.learning.service import LearningService
from modules.factory.publishing.service import PublishingService
from modules.factory.store import Database

NOW = "2026-09-17T12:00:00+00:00"
SHA = "ab" * 32


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _experiment(db, eid="exp-1", seed="seed-1", rev=1,
                template="fmt-1"):
    with db.uow() as u:
        u.records.put(ExperimentRevision(
            schema_version="experiment_revision.v1",
            id=f"{eid}-r{rev}", created_at=NOW, experiment_id=eid,
            revision=rev, status="accepted", seed_id=seed,
            template_ref=template, content_hash=f"h-{eid}-{rev}"))
        for vk in "ABCD":
            u.records.put(VariantPlan(
                schema_version="variant_plan.v1",
                id=f"vp-{eid}-{vk.lower()}", created_at=NOW,
                experiment_id=eid, experiment_revision=rev,
                variant_key=vk,
                hypothesis="" if vk == "A" else "h",
                changed_factor="" if vk == "A" else "hook",
                status="planned"))


def _publish(db, eid, vals, horizon="48h"):
    """Register a manual post + snapshot per variant.
    vals: {variant: {metric: value}} — {} means no snapshot."""
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
        snap = MetricSnapshot(
            schema_version="metric_snapshot.v1",
            id=f"snap-{pid}-{horizon}", created_at=NOW,
            publication_id=pid, post_id=f"yt-{pid}", horizon=horizon,
            query_version="f32.v1",
            metrics=metrics,
            availability={k: "ok" for k in metrics},
            completeness="complete", observed_at=NOW)
        with db.uow() as u:
            u.records.put(snap)


def _policy(svc, eid="exp-1", rev=1, **kw):
    args = dict(policy_version="p1", primary_metric="views",
                horizon="48h", min_exposure=0, practical_lift=0.3)
    args.update(kw)
    return svc.freeze_policy(eid, rev, **args)


def _rich(v, imp=5000, avp=70.0):
    return {"views": v, "thumbnail_impressions": imp,
            "avg_view_pct": avp}


# -------------------------------------------------------- policy --

def test_decide_requires_frozen_policy(db):
    _experiment(db)
    svc = LearningService(db)
    with pytest.raises(ContractError) as e:
        svc.decide("exp-1", 1)
    assert e.value.code == "policy_not_frozen"


def test_policy_cannot_freeze_after_publication(db):
    _experiment(db)
    _publish(db, "exp-1", {"a": _rich(1000)})
    svc = LearningService(db)
    with pytest.raises(ContractError) as e:
        _policy(svc)
    assert e.value.code == "policy_after_publication"


# -------------------------------------------------------- decide --

def test_provisional_winner_on_practical_lift(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    assert d["conclusion"] == "provisional_winner"
    assert d["winner"] == "B"
    lifts = {c["variant"]: c["lift"] for c in d["comparisons"]}
    assert lifts["B"] == pytest.approx(0.4)
    assert lifts["D"] == pytest.approx(-0.2)


def test_waiting_for_data_on_missing_coverage(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": None})
    d = svc.decide("exp-1", 1)
    assert d["conclusion"] == "waiting_for_data"
    assert d["winner"] == ""


def test_insufficient_exposure(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, min_exposure=100000)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    assert d["conclusion"] == "insufficient_exposure"


def test_zero_control_is_defined_not_infinite(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(0, imp=5000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    assert d["conclusion"] == "inconclusive"
    assert any("zero_baseline" in l for l in d["limitations"])


def test_no_improvement_when_all_treatments_lose(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(900),
        "c": _rich(800), "d": _rich(700)})
    d = svc.decide("exp-1", 1)
    assert d["conclusion"] == "no_improvement"
    assert d["winner"] == ""


def test_guardrail_failure_removes_candidate(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, guardrails={"avg_view_pct": 50.0})
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400, avp=40.0),
        "c": _rich(1100), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    # B has lift but fails the guardrail; C's 0.1 < 0.3 → inconclusive
    assert d["conclusion"] == "inconclusive"
    gc = {c["variant"]: c.get("guardrails")
          for c in d["comparisons"]}
    assert "avg_view_pct:40.0<50.0" in gc["B"]


def test_comparison_rule_all(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, comparison_rule="all")
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(1350), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    assert d["conclusion"] == "inconclusive"   # D didn't lift


# ------------------------------------------------- idempotent/revise --

def test_identical_recompute_is_idempotent(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d1 = svc.decide("exp-1", 1)
    d2 = svc.decide("exp-1", 1)
    assert d2.get("_idempotent") is True
    n = db.uow().conn.execute(
        "SELECT COUNT(*) c FROM records WHERE kind='decision'"
    ).fetchone()["c"]
    assert n == 1


def test_new_data_revises_decision(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d1 = svc.decide("exp-1", 1)
    # D's coverage completes later with better numbers
    pid = "pub-exp-1-d"
    snap = MetricSnapshot(
        schema_version="metric_snapshot.v1",
        id="snap-pub-exp-1-d-48h", created_at=NOW,
        publication_id=pid, post_id="yt-x", horizon="48h",
        query_version="f32.v1", metrics=_rich(1600),
        availability={"views": "ok"}, completeness="complete",
        observed_at="2026-09-18T00:00:00+00:00")
    row = db.uow().records.get("metricsnapshot", snap.id)
    body = json.loads(row["body"])
    body["metrics"]["views"] = 1600
    with db.uow() as u:
        u.conn.execute(
            "UPDATE records SET body=? WHERE kind='metricsnapshot' "
            "AND id=?", (json.dumps(body), snap.id))
    d2 = svc.decide("exp-1", 1)
    assert d2["id"] != d1["id"]
    assert d2["conclusion"] == "provisional_winner"
    assert d2["winner"] == "D"
    old = db.uow().records.get("decision", d1["id"])
    assert json.loads(old["body"])["superseded_by"] == d2["id"]


# ------------------------------------------------ independent count --

def test_siblings_count_as_one_experiment(db):
    _experiment(db, "exp-1", seed="seed-1")
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(1350), "d": _rich(1300)})
    svc.decide("exp-1", 1)
    out = svc.promote("fmt-1", min_independent=2)
    assert out["independent_experiments"] == 1
    assert out["status"] == "promising"          # NOT proven


def test_two_independent_seeds_prove_format(db):
    svc = LearningService(db)
    for eid, seed in (("exp-1", "seed-1"), ("exp-2", "seed-2")):
        _experiment(db, eid, seed=seed)
        _policy(svc, eid=eid)
        _publish(db, eid, {
            "a": _rich(1000), "b": _rich(1400),
            "c": _rich(900), "d": _rich(800)})
        svc.decide(eid, 1)
    out = svc.promote("fmt-1", min_independent=2)
    assert out["independent_experiments"] == 2
    assert out["status"] == "proven"
    assert out["seeds"] == ["seed-1", "seed-2"]


# ------------------------------------------------------ hypotheses --

def test_hypotheses_searchable_and_attributed(db):
    svc = LearningService(db)
    svc.add_hypothesis("h-1", claim="shorter hooks retain better",
                       evidence_ids=["dec-1"], uncertainty="medium",
                       status="accepted", source="decision:dec-1")
    svc.add_hypothesis("h-2", claim="music drives shares",
                       uncertainty="high", source="operator:ting",
                       attributed_to="ting")
    found = svc.hypotheses("hook")
    assert len(found) == 1 and found[0]["id"] == "h-1"
    svc.override_hypothesis("h-1", status="retired",
                            operator="ting", note="later data weak")
    h = svc.hypotheses("hook")[0]
    assert h["status"] == "retired"
    assert h["attributed_to"] == "ting"


# -------------------------------------------------------- summary --

def test_summary_is_descriptive_never_causal(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    text = svc.summary(d["id"])
    assert "observational" in text
    assert "provisional_winner" in text
    for causal in ("proves", "statistically significant",
                   "caused", "p <", "p-value"):
        assert causal not in text.lower()


def test_decision_references_snapshots_and_policy(db):
    _experiment(db)
    svc = LearningService(db)
    _policy(svc)
    _publish(db, "exp-1", {
        "a": _rich(1000), "b": _rich(1400),
        "c": _rich(900), "d": _rich(800)})
    d = svc.decide("exp-1", 1)
    assert len(d["evidence_ids"]) == 4
    assert d["policy_version"] == "p1"
    assert d["inputs_hash"]
