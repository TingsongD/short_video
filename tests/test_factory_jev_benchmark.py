from copy import deepcopy

import pytest

from modules.factory.domain.errors import ContractError


CASE_IDS = (
    "rapid_cuts_two_frame",
    "continuous_footage",
    "repeated_callback",
    "quiet_setup_payoff",
    "vfr_timing",
    "silence",
    "weak_rhythm",
    "clear_beats",
    "audiovisual_disagreement",
)


def _cases(*, provider_observed=True, prune=True):
    cases = []
    for index, case_id in enumerate(CASE_IDS):
        ids = [f"{case_id}:mandatory", f"{case_id}:relevant",
               f"{case_id}:redundant"]
        cases.append({
            "id": case_id,
            "candidate_ids": ids,
            "mandatory_ids": [ids[0]],
            "relevant_ids": ids[:2],
            "deterministic_selected_ids": ids,
            "jev_selected_ids": ids[:2] if prune and index == 0 else ids,
            "provider_observed": provider_observed,
            "latency_ms": 20 + index,
            "cost": {
                "jev_usd_micros": 2,
                "jev_basis": "recorded_usage" if provider_observed
                else "estimated_quote",
                "downstream_without_jev_usd_micros": 50,
                "downstream_with_jev_usd_micros": (
                    10 if prune and index == 0 else 50
                ),
                "downstream_basis": "estimated_quote",
            },
        })
    return cases


def test_complete_shadow_benchmark_can_qualify_active_selection():
    from modules.factory.analysis.jev_benchmark import evaluate_shadow_benchmark
    from modules.factory.analysis.jev import select_evidence

    report = evaluate_shadow_benchmark(_cases())
    assert report["version"] == "jev_selection_benchmark.v1"
    assert report["case_ids"] == list(CASE_IDS)
    assert report["metrics"] == {
        "mandatory_total": 9,
        "deterministic_mandatory_loss": 0,
        "jev_mandatory_loss": 0,
        "relevant_total": 18,
        "deterministic_relevant_loss": 0,
        "jev_relevant_loss": 0,
        "deterministic_selected": 27,
        "jev_selected": 26,
        "optional_reduction": 1,
        "provider_observations": 9,
        "latency_ms": {"p50": 24, "p95": 28, "max": 28},
        "cost_usd_micros": {
            "jev_recorded": 18,
            "jev_estimated": 0,
            "downstream_baseline_estimated": 450,
            "downstream_with_jev_estimated": 410,
            "total_with_jev_estimated": 428,
            "net_savings_estimated": 22,
        },
    }
    assert report["qualified"] is True
    assert report["benefit_observed"] is True

    candidates = [
        {"id": "required", "summary": "Opening context.",
         "mandatory": True},
        {"id": "noise", "summary": "Redundant optional measurement.",
         "mandatory": False},
    ]
    assert select_evidence(
        candidates, {"noise": "optional"}, mode="active",
        benchmark=report,
    ) == ["required"]


def test_unmeasured_or_no_benefit_benchmark_keeps_active_mode_disabled():
    from modules.factory.analysis.jev_benchmark import evaluate_shadow_benchmark
    from modules.factory.analysis.jev import select_evidence

    candidates = [
        {"id": "required", "summary": "Opening context.",
         "mandatory": True},
        {"id": "noise", "summary": "Optional context.",
         "mandatory": False},
    ]
    for report in (
        evaluate_shadow_benchmark(_cases(provider_observed=False)),
        evaluate_shadow_benchmark(_cases(prune=False)),
    ):
        assert report["qualified"] is False
        with pytest.raises(ContractError, match="jev_active_unqualified"):
            select_evidence(candidates, {"noise": "optional"},
                            mode="active", benchmark=report)


def test_active_mode_rejects_tampered_or_incomplete_benchmark_evidence():
    from modules.factory.analysis.jev_benchmark import evaluate_shadow_benchmark
    from modules.factory.analysis.jev import select_evidence

    candidates = [
        {"id": "required", "summary": "Opening context.",
         "mandatory": True},
        {"id": "noise", "summary": "Optional context.",
         "mandatory": False},
    ]
    report = evaluate_shadow_benchmark(_cases())
    tampered = deepcopy(report)
    tampered["metrics"]["jev_relevant_loss"] = 1
    incomplete = evaluate_shadow_benchmark(_cases()[:-1])
    for proof in (tampered, incomplete, {
            "qualified": True, "mandatory_loss": 0,
            "benefit_observed": True, "evidence_sha256": "d" * 64}):
        with pytest.raises(ContractError, match="jev_active_unqualified"):
            select_evidence(candidates, {"noise": "optional"},
                            mode="active", benchmark=proof)
