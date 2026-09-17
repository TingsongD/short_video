"""Frozen contract schema versions (handover §7.1).

Every factory record carries a schema_version string registered here.
Bumping a version requires a migration or adapter — readers must not
silently accept unknown versions.
"""

SCHEMA_VERSIONS = {
    "seed.v1": "Seed",
    "metric_observation.v1": "MetricObservation",
    "product_snapshot.v1": "ProductSnapshot",
    "reference_blueprint.v1": "ReferenceBlueprint",
    "format_template.v1": "FormatTemplate",
    "experiment_revision.v1": "ExperimentRevision",
    "variant_plan.v1": "VariantPlan",
    "generation_request.v1": "GenerationRequest",
    "price_assessment.v1": "PriceAssessment",
    "authorization.v1": "Authorization",
    "job.v1": "Job",
    "attempt.v1": "Attempt",
    "artifact.v1": "Artifact",
    "asset_use.v1": "AssetUse",
    "review.v1": "Review",
    "delivery.v1": "Delivery",
    "publication.v1": "Publication",
    "metric_snapshot.v1": "MetricSnapshot",
    "decision.v1": "Decision",
    "decision_policy.v1": "DecisionPolicy",
    "hypothesis.v1": "Hypothesis",
    "outbox_event.v1": "OutboxEvent",
    "experiment_state.v1": "ExperimentState",
    "variant_state.v1": "VariantState",
    "segment_state.v1": "SegmentState",
}

from ...domain.errors import ContractError  # noqa: E402


def check_version(version):
    if version not in SCHEMA_VERSIONS:
        raise ContractError("unsupported_schema_version", "schema_version",
                            version)
    return version
