"""Auditable shadow benchmark gate for optional Jev evidence selection.

The report compares two *selection results* over a frozen labeled matrix.  It
does not call providers and it does not infer that fewer candidates are better:
active eligibility requires zero labeled-context loss, recorded Jev observations,
bounded latency, and estimated downstream savings larger than Jev's own cost.
"""
from copy import deepcopy
import math

from .jev import MODEL
from ..domain.errors import ContractError
from ..domain.records import content_hash


VERSION = "jev_selection_benchmark.v1"
RUBRIC_ID = "optional_evidence.v1"
REQUIRED_CASES = (
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
THRESHOLDS = {
    "mandatory_loss": 0,
    "relevant_loss": 0,
    "minimum_optional_reduction": 1,
    "minimum_net_savings_usd_micros": 1,
    "maximum_p95_latency_ms": 2000,
    "provider_observation_each_case": True,
}


def _ids(value, field, candidates):
    if (not isinstance(value, list) or len(value) != len(set(value))
            or any(not isinstance(item, str) or not item
                   or item not in candidates for item in value)):
        raise ContractError("invalid_jev_benchmark", field)
    return value


def _case(value):
    expected = {
        "id", "candidate_ids", "mandatory_ids", "relevant_ids",
        "deterministic_selected_ids", "jev_selected_ids",
        "provider_observed", "latency_ms", "cost",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ContractError("invalid_jev_benchmark", "case")
    ident = value["id"]
    if ident not in REQUIRED_CASES:
        raise ContractError("invalid_jev_benchmark", "case_id")
    candidates = value["candidate_ids"]
    if (not isinstance(candidates, list) or not candidates
            or len(candidates) != len(set(candidates))
            or any(not isinstance(item, str) or not item
                   for item in candidates)):
        raise ContractError("invalid_jev_benchmark", "candidate_ids")
    mandatory = _ids(value["mandatory_ids"], "mandatory_ids", candidates)
    relevant = _ids(value["relevant_ids"], "relevant_ids", candidates)
    deterministic = _ids(value["deterministic_selected_ids"],
                         "deterministic_selected_ids", candidates)
    jev = _ids(value["jev_selected_ids"], "jev_selected_ids", candidates)
    if not set(mandatory).issubset(relevant):
        raise ContractError("invalid_jev_benchmark", "relevant_ids")
    observed = value["provider_observed"]
    latency = value["latency_ms"]
    if type(observed) is not bool or type(latency) is not int or latency < 0:
        raise ContractError("invalid_jev_benchmark", "observation")
    cost = value["cost"]
    if (not isinstance(cost, dict) or set(cost) != {
            "jev_usd_micros", "jev_basis",
            "downstream_without_jev_usd_micros",
            "downstream_with_jev_usd_micros", "downstream_basis"}):
        raise ContractError("invalid_jev_benchmark", "cost")
    amounts = (cost["jev_usd_micros"],
               cost["downstream_without_jev_usd_micros"],
               cost["downstream_with_jev_usd_micros"])
    if any(type(amount) is not int or amount < 0 for amount in amounts):
        raise ContractError("invalid_jev_benchmark", "cost")
    if (cost["jev_basis"] != (
            "recorded_usage" if observed else "estimated_quote")
            or cost["downstream_basis"] != "estimated_quote"):
        raise ContractError("invalid_jev_benchmark", "cost_basis")
    return deepcopy(value)


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def evaluate_shadow_benchmark(cases):
    """Return a deterministic, self-verifying benchmark report.

    Provider observations and downstream quotes are inputs gathered by a
    separate benchmark harness.  This evaluator only validates and scores them;
    it has no credentials, transport, database, or production side effects.
    """
    if not isinstance(cases, list) or not cases:
        raise ContractError("invalid_jev_benchmark", "cases")
    normalized = [_case(case) for case in cases]
    if len({case["id"] for case in normalized}) != len(normalized):
        raise ContractError("invalid_jev_benchmark", "duplicate_case")
    order = {ident: index for index, ident in enumerate(REQUIRED_CASES)}
    normalized.sort(key=lambda case: order[case["id"]])

    mandatory_total = deterministic_mandatory_loss = jev_mandatory_loss = 0
    relevant_total = deterministic_relevant_loss = jev_relevant_loss = 0
    deterministic_selected = jev_selected = provider_observations = 0
    latencies = []
    jev_recorded = jev_estimated = baseline = downstream_with = 0
    case_results = []
    for case in normalized:
        mandatory = set(case["mandatory_ids"])
        relevant = set(case["relevant_ids"])
        deterministic = set(case["deterministic_selected_ids"])
        selected = set(case["jev_selected_ids"])
        d_mandatory = len(mandatory - deterministic)
        j_mandatory = len(mandatory - selected)
        d_relevant = len(relevant - deterministic)
        j_relevant = len(relevant - selected)
        mandatory_total += len(mandatory)
        relevant_total += len(relevant)
        deterministic_mandatory_loss += d_mandatory
        jev_mandatory_loss += j_mandatory
        deterministic_relevant_loss += d_relevant
        jev_relevant_loss += j_relevant
        deterministic_selected += len(deterministic)
        jev_selected += len(selected)
        provider_observations += int(case["provider_observed"])
        latencies.append(case["latency_ms"])
        cost = case["cost"]
        if cost["jev_basis"] == "recorded_usage":
            jev_recorded += cost["jev_usd_micros"]
        else:
            jev_estimated += cost["jev_usd_micros"]
        baseline += cost["downstream_without_jev_usd_micros"]
        downstream_with += cost["downstream_with_jev_usd_micros"]
        case_results.append({
            "id": case["id"],
            "mandatory_loss": j_mandatory,
            "relevant_loss": j_relevant,
            "deterministic_selected": len(deterministic),
            "jev_selected": len(selected),
            "provider_observed": case["provider_observed"],
            "latency_ms": case["latency_ms"],
            "cost": deepcopy(cost),
        })
    total_with = downstream_with + jev_recorded + jev_estimated
    metrics = {
        "mandatory_total": mandatory_total,
        "deterministic_mandatory_loss": deterministic_mandatory_loss,
        "jev_mandatory_loss": jev_mandatory_loss,
        "relevant_total": relevant_total,
        "deterministic_relevant_loss": deterministic_relevant_loss,
        "jev_relevant_loss": jev_relevant_loss,
        "deterministic_selected": deterministic_selected,
        "jev_selected": jev_selected,
        "optional_reduction": deterministic_selected - jev_selected,
        "provider_observations": provider_observations,
        "latency_ms": {
            "p50": _percentile(latencies, .50),
            "p95": _percentile(latencies, .95),
            "max": max(latencies),
        },
        "cost_usd_micros": {
            "jev_recorded": jev_recorded,
            "jev_estimated": jev_estimated,
            "downstream_baseline_estimated": baseline,
            "downstream_with_jev_estimated": downstream_with,
            "total_with_jev_estimated": total_with,
            "net_savings_estimated": baseline - total_with,
        },
    }
    case_ids = [case["id"] for case in normalized]
    missing = [ident for ident in REQUIRED_CASES if ident not in case_ids]
    reasons = []
    if missing:
        reasons.append("required_cases_missing")
    if provider_observations != len(REQUIRED_CASES):
        reasons.append("provider_observations_incomplete")
    if deterministic_mandatory_loss or deterministic_relevant_loss:
        reasons.append("deterministic_baseline_invalid")
    if jev_mandatory_loss:
        reasons.append("mandatory_context_lost")
    if jev_relevant_loss:
        reasons.append("labeled_relevance_lost")
    if metrics["optional_reduction"] < THRESHOLDS["minimum_optional_reduction"]:
        reasons.append("selection_benefit_not_observed")
    if (metrics["cost_usd_micros"]["net_savings_estimated"]
            < THRESHOLDS["minimum_net_savings_usd_micros"]):
        reasons.append("net_cost_benefit_not_observed")
    if metrics["latency_ms"]["p95"] > THRESHOLDS["maximum_p95_latency_ms"]:
        reasons.append("latency_limit_exceeded")
    body = {
        "version": VERSION,
        "model": MODEL,
        "rubric": RUBRIC_ID,
        "thresholds": deepcopy(THRESHOLDS),
        "case_ids": case_ids,
        "case_matrix_sha256": content_hash(normalized),
        "cases": normalized,
        "case_results": case_results,
        "metrics": metrics,
        "benefit_observed": (
            metrics["optional_reduction"] > 0
            and metrics["cost_usd_micros"]["net_savings_estimated"] > 0
        ),
        "qualified": not reasons,
        "disqualifiers": reasons,
    }
    return {**body, "report_sha256": content_hash(body)}


def validate_active_benchmark(report):
    """Require the exact report generated from its retained case evidence."""
    try:
        if not isinstance(report, dict) or not isinstance(report["cases"], list):
            raise ValueError()
        rebuilt = evaluate_shadow_benchmark(report["cases"])
        if report != rebuilt or rebuilt["qualified"] is not True:
            raise ValueError()
    except (KeyError, TypeError, ValueError, ContractError):
        raise ContractError("jev_active_unqualified", "benchmark") from None
    return deepcopy(rebuilt)
