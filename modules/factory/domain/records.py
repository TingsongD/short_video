"""Factory domain records (F02; handover §7.2).

Every durable record: schema_version, stable ID, revision where
applicable, UTC creation, links to exact input revisions. Media references
are artifact IDs + hashes. Validators return typed ContractError lists;
callers use validate() or validate_or_raise().
"""
import hashlib
import json
import re
from dataclasses import dataclass, field, asdict

from .clocks import RationalRate, FrameInterval, check_partition
from .errors import ContractError
from .money import Money, UNITS

ID_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,80}$")
PROVENANCES = {"jimeng_canvas", "google_vertex", "manual", "stock",
               "elevenlabs", "seed_source", "shopify", "generated_other"}
PROVIDERS = {"jimeng_canvas", "google_vertex"}
VARIANT_KEYS = ("A", "B", "C", "D")
JOB_STATES = {"waiting_dependencies", "ready", "reserved", "dispatching",
              "accepted", "running", "output_available", "downloaded",
              "awaiting_review", "succeeded", "unknown", "blocked",
              "failed", "cancel_requested", "cancelled"}


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str)


def content_hash(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _id_errors(errors, value, field_name):
    if not isinstance(value, str) or not ID_RE.match(value):
        errors.append(ContractError("malformed_id", field_name,
                                    repr(value)[:60]))


@dataclass
class Record:
    schema_version: str = ""
    id: str = ""
    created_at: str = ""

    def validate(self) -> list:
        errors = []
        if not self.schema_version:
            errors.append(ContractError("missing_schema_version",
                                        "schema_version"))
        _id_errors(errors, self.id, "id")
        if not self.created_at:
            errors.append(ContractError("missing_time", "created_at"))
        return errors

    def validate_or_raise(self):
        errs = self.validate()
        if errs:
            raise errs[0]
        return self

    def to_dict(self):
        return {k: v for k, v in asdict(self).items()}

    def hash(self):
        return content_hash(self.to_dict())


# ---------------------------------------------------------------- seeds

@dataclass
class Seed(Record):
    revision: int = 0                # append-only provenance/metadata updates
    platform: str = ""
    canonical_url: str = ""
    native_id: str = ""
    creator_id: str = ""
    source_asset_id: str = ""
    original_url: str = ""
    # metadata_only | needs_source_media | media_ready
    evidence_status: str = "metadata_only"
    title: str = ""
    provenance: list = field(default_factory=list)  # url forms + via + when
    metadata: dict = field(default_factory=dict)    # provider-observed fields
    metadata_fetched_at: str = ""

    def validate(self):
        e = super().validate()
        if self.platform not in ("youtube", "tiktok", "instagram", "local"):
            e.append(ContractError("unsupported_platform", "platform",
                                   self.platform))
        if self.platform != "local" and not self.canonical_url:
            e.append(ContractError("missing_field", "canonical_url"))
        if self.evidence_status == "media_ready" and not self.source_asset_id:
            e.append(ContractError("missing_field", "source_asset_id",
                                   "media_ready requires a source artifact"))
        if self.evidence_status not in ("metadata_only",
                                        "needs_source_media", "media_ready"):
            e.append(ContractError("bad_evidence_status", "evidence_status",
                                   self.evidence_status))
        return e


@dataclass
class MetricObservation(Record):
    """Seed performance observation. Unknown counts are null + reason,
    never zero."""
    seed_id: str = ""
    observed_at: str = ""
    views: object = None
    likes: object = None
    followers: object = None
    unknown_reason: str = ""
    baseline_method: str = ""        # provider_average | local_cohort | none
    cohort_size: object = None
    cohort_mean_views: object = None
    cohort_median_views: object = None
    provider_score: object = None    # provider's own outlier score, kept distinct
    age_days: object = None

    def validate(self):
        e = super().validate()
        _id_errors(e, self.seed_id, "seed_id")
        if self.views is None and not self.unknown_reason:
            e.append(ContractError("unknown_needs_reason", "unknown_reason"))
        for f in ("views", "likes", "followers", "cohort_size",
                  "cohort_mean_views", "cohort_median_views"):
            v = getattr(self, f)
            if v is not None and (type(v) not in (int, float) or v < 0):
                e.append(ContractError("invalid_count", f, repr(v)))
        return e

    def follower_multiple(self):
        if self.views is None or self.followers in (None, 0):
            return None
        return self.views / self.followers

    def median_multiple(self):
        if self.views is None or self.cohort_median_views in (None, 0):
            return None
        return self.views / self.cohort_median_views


# -------------------------------------------------------------- products

@dataclass
class ProductSnapshot(Record):
    shop: str = ""
    product_id: str = ""
    variant_id: str = ""
    title: str = ""
    options: dict = field(default_factory=dict)
    price: object = None             # Money or None
    available: object = None         # bool | None(unknown)
    media_artifact_ids: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    observed_at: str = ""
    pagination_complete: bool = False

    def validate(self):
        e = super().validate()
        if not self.product_id:
            e.append(ContractError("missing_field", "product_id"))
        if self.price is not None and not isinstance(self.price, Money):
            e.append(ContractError("invalid_price", "price"))
        if not self.pagination_complete:
            e.append(ContractError("pagination_incomplete", "media_artifact_ids",
                                   "snapshot cannot claim complete media"))
        return e


# ------------------------------------------------------------- blueprint

@dataclass
class Beat:
    id: str = ""
    source: FrameInterval = None
    target: FrameInterval = None
    role: str = ""
    speech_segment_id: str = ""
    visual_event: str = ""
    evidence_ids: list = field(default_factory=list)
    confidence: str = "reviewed"     # reviewed | uncertain | unresolved

    def to_dict(self):
        return {"id": self.id, "role": self.role,
                "source": self.source.to_dict() if self.source else None,
                "target": self.target.to_dict() if self.target else None,
                "speech_segment_id": self.speech_segment_id,
                "visual_event": self.visual_event,
                "evidence_ids": self.evidence_ids,
                "confidence": self.confidence}


@dataclass
class ReferenceBlueprint(Record):
    seed_id: str = ""
    revision: int = 0
    status: str = "draft"            # draft | accepted | superseded
    parent_hash: str = ""
    clock: RationalRate = None
    target_frames: int = 0
    beats: list = field(default_factory=list)      # list[Beat]
    speech: dict = field(default_factory=dict)
    visual_systems: dict = field(default_factory=dict)
    audio: dict = field(default_factory=dict)
    adaptation: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    content_hash: str = ""

    def validate(self):
        e = super().validate()
        _id_errors(e, self.seed_id, "seed_id")
        if self.revision < 1:
            e.append(ContractError("invalid_revision", "revision"))
        if self.clock is None or self.target_frames <= 0:
            e.append(ContractError("missing_clock", "target_frames"))
            return e
        for b in self.beats:
            if b.target is None:
                e.append(ContractError("missing_field", f"beats[{b.id}].target"))
        targets = [b.target for b in self.beats if b.target is not None]
        e.extend(check_partition(targets, self.target_frames))
        if self.status == "accepted" and not self.content_hash:
            e.append(ContractError("missing_hash", "content_hash",
                                   "accepted blueprint must be hashed"))
        return e

    def to_dict(self):
        d = super().to_dict()
        d["clock"] = {"num": self.clock.num, "den": self.clock.den} \
            if self.clock else None
        d["beats"] = [b.to_dict() for b in self.beats]
        return d


# -------------------------------------------------------------- template

@dataclass
class Slot:
    id: str = ""
    kind: str = ""                   # hook|product|proof|cta|transition
    min_frames: int = 0
    max_frames: int = 0
    required_reference: str = ""     # image|video|none


@dataclass
class FormatTemplate(Record):
    revision: int = 0
    status: str = "candidate"        # candidate | proven | retired
    slots: list = field(default_factory=list)      # list[Slot]
    constraints: dict = field(default_factory=dict)
    renderer: str = "hypit"          # hypit | ffmpeg_fast
    derived_from_blueprint: str = ""

    def validate(self):
        e = super().validate()
        if self.renderer not in ("hypit", "ffmpeg_fast"):
            e.append(ContractError("unknown_renderer", "renderer",
                                   self.renderer))
        for s in self.slots:
            if s.min_frames < 0 or (s.max_frames and s.max_frames < s.min_frames):
                e.append(ContractError("invalid_slot", f"slots[{s.id}]"))
        return e


# ------------------------------------------------------------ experiment

@dataclass
class ProviderPolicy:
    choice: str = "jimeng"           # jimeng | vertex | jimeng_with_vertex_fallback
    allowed_models: dict = field(default_factory=dict)  # provider -> [models]
    fallback_provider: str = ""
    automatic_fallback: bool = False
    max_fallback_attempts: int = 0
    native_audio_policy: str = "strip"  # strip | select | keep

    def validate(self):
        e = []
        if self.choice not in ("jimeng", "vertex",
                               "jimeng_with_vertex_fallback"):
            e.append(ContractError("unknown_policy", "choice", self.choice))
        if self.fallback_provider and self.fallback_provider not in PROVIDERS:
            e.append(ContractError("unknown_provider", "fallback_provider",
                                   self.fallback_provider))
        return e


@dataclass
class ExperimentRevision(Record):
    """Immutable once accepted: blueprint+template hashes, products,
    presenter/voice, provider policy, segments, asset selections, music,
    captions, output clock, packaging."""
    experiment_id: str = ""
    revision: int = 0
    status: str = "draft"
    parent_revision: int = 0
    parent_hash: str = ""
    seed_id: str = ""
    blueprint_hash: str = ""
    template_ref: str = ""
    product_snapshot_ids: list = field(default_factory=list)
    presenter_ref: str = ""
    voice: dict = field(default_factory=dict)      # id, model, settings frozen
    provider_policy: ProviderPolicy = None
    segments: list = field(default_factory=list)   # script/beat allocations
    shared_asset_ids: list = field(default_factory=list)
    music: dict = field(default_factory=dict)
    captions: dict = field(default_factory=dict)
    output_clock: dict = field(default_factory=dict)
    packaging: dict = field(default_factory=dict)
    content_hash: str = ""

    def validate(self):
        e = super().validate()
        _id_errors(e, self.experiment_id, "experiment_id")
        if self.revision < 1:
            e.append(ContractError("invalid_revision", "revision"))
        if self.provider_policy:
            e.extend(self.provider_policy.validate())
        if self.status == "accepted" and not self.content_hash:
            e.append(ContractError("missing_hash", "content_hash"))
        return e


@dataclass
class VariantPlan(Record):
    """One declared treatment branching from the frozen control."""
    experiment_id: str = ""
    experiment_revision: int = 0
    variant_key: str = ""
    control_variant_key: str = "A"
    hypothesis: str = ""
    changed_factor: str = ""          # hook | body | ending | duration | ...
    allowed_regions: list = field(default_factory=list)   # FrameInterval
    allowed_fields: list = field(default_factory=list)
    locked_fields: list = field(default_factory=list)
    target_frames: int = 0
    primary_metric: str = ""
    budget_category: str = "experiment_variations"
    status: str = "draft"

    def validate(self):
        e = super().validate()
        _id_errors(e, self.experiment_id, "experiment_id")
        if self.variant_key not in VARIANT_KEYS:
            e.append(ContractError("bad_variant", "variant_key",
                                   self.variant_key))
        if self.variant_key != "A":
            if not self.hypothesis:
                e.append(ContractError("missing_field", "hypothesis"))
            if not self.changed_factor:
                e.append(ContractError("missing_field", "changed_factor"))
            if not self.allowed_regions:
                e.append(ContractError("missing_field", "allowed_regions",
                                       "a treatment must declare its region"))
            if not self.locked_fields:
                e.append(ContractError("missing_field", "locked_fields"))
        for r in self.allowed_regions:
            if not isinstance(r, FrameInterval):
                e.append(ContractError("invalid_region", "allowed_regions"))
            elif self.target_frames and r.end > self.target_frames:
                e.append(ContractError("region_out_of_range",
                                       "allowed_regions"))
        return e

    def regions_dict(self):
        return [r.to_dict() for r in self.allowed_regions]


# ------------------------------------------------------------ generation

@dataclass
class GenerationRequest(Record):
    """Provider-neutral request; provider payloads stay in adapters."""
    experiment_id: str = ""
    experiment_revision: int = 0
    variant_key: str = ""
    segment_id: str = ""
    prompt: str = ""
    provider: str = ""
    model: str = ""
    route: str = ""
    billing_scope: str = ""           # account / project reference (no secrets)
    region: str = ""
    reference_artifact_ids: list = field(default_factory=list)
    reference_roles: dict = field(default_factory=dict)
    requested_duration_s: float = 0.0
    required_usable_s: float = 0.0
    aspect: str = "9:16"
    resolution: str = "1080x1920"
    output_count: int = 1
    native_audio_policy: str = "strip"
    request_hash: str = ""

    def validate(self):
        e = super().validate()
        if self.provider and self.provider not in PROVIDERS:
            e.append(ContractError("unknown_provider", "provider",
                                   self.provider))
        if self.required_usable_s > self.requested_duration_s:
            e.append(ContractError("usable_exceeds_requested",
                                   "required_usable_s"))
        if self.output_count != 1:
            e.append(ContractError("multi_output", "output_count",
                                   "one result per request"))
        return e

    def finalize_hash(self):
        """Canonical identity over generation-relevant fields."""
        d = self.to_dict()
        d.pop("request_hash", None)
        d.pop("created_at", None)
        self.request_hash = content_hash(d)
        return self.request_hash


@dataclass
class PriceAssessment(Record):
    """native_quote (Canvas) or usage_estimate (Vertex). Never both."""
    kind: str = ""                   # native_quote | usage_estimate
    request_hash: str = ""
    provider: str = ""
    model: str = ""
    unit: str = ""
    amount: int = 0                  # estimated/quoted amount
    reserve_amount: int = 0          # conservative reservation
    rate_basis: str = ""             # dated rate/version reference
    valid_until: str = ""
    provisional: bool = False

    def validate(self):
        e = super().validate()
        if self.kind not in ("native_quote", "usage_estimate"):
            e.append(ContractError("unknown_price_kind", "kind", self.kind))
        if self.unit not in UNITS:
            e.append(ContractError("unknown_unit", "unit", self.unit))
        for f in ("amount", "reserve_amount"):
            v = getattr(self, f)
            if type(v) is not int or v < 0:
                e.append(ContractError("invalid_amount", f, repr(v)))
        if not self.request_hash:
            e.append(ContractError("missing_field", "request_hash"))
        return e


@dataclass
class Authorization(Record):
    """Spend authority bound to a plan hash. Does not grow with balance."""
    scope_hash: str = ""             # hash of the authorized experiment revision
    allowed_providers: list = field(default_factory=list)
    allowed_models: dict = field(default_factory=dict)
    allowed_input_modes: list = field(default_factory=list)
    caps: dict = field(default_factory=dict)         # unit -> int|None
    correction_allowance: dict = field(default_factory=dict)
    automatic_continuation: bool = False
    fallback_order: list = field(default_factory=list)
    max_fallback_attempts: int = 0
    publication_authorized: bool = False
    authorizing_action: str = ""
    valid_until: str = ""
    status: str = "not_authorized"   # not_authorized | authorized | revoked | expired

    def validate(self):
        e = super().validate()
        if self.status == "authorized":
            if not self.scope_hash:
                e.append(ContractError("missing_field", "scope_hash"))
            for unit, cap in self.caps.items():
                if unit not in UNITS:
                    e.append(ContractError("unknown_unit", f"caps.{unit}", unit))
                if cap is not None and (type(cap) is not int or cap < 0):
                    e.append(ContractError("invalid_cap", f"caps.{unit}"))
        for p in self.allowed_providers:
            if p not in PROVIDERS:
                e.append(ContractError("unknown_provider",
                                       "allowed_providers", p))
        return e


# ------------------------------------------------------------------ jobs

@dataclass
class Job(Record):
    logical_key: str = ""            # unique operation identity per revision
    phase: str = ""
    experiment_id: str = ""
    revision: int = 0
    variant_key: str = ""
    depends_on: list = field(default_factory=list)
    status: str = "waiting_dependencies"
    retry_class: str = "none"        # none | read | transfer | bounded_paid
    lease_owner: str = ""
    lease_expires: str = ""
    fencing_token: int = 0
    blocked_reason: str = ""

    def validate(self):
        e = super().validate()
        if not self.logical_key:
            e.append(ContractError("missing_field", "logical_key"))
        if self.status not in JOB_STATES:
            e.append(ContractError("bad_job_state", "status", self.status))
        return e


@dataclass
class Attempt(Record):
    job_id: str = ""
    attempt_seq: int = 0             # monotonic per job
    provider: str = ""
    model: str = ""
    route: str = ""
    request_hash: str = ""
    remote_id: str = ""              # provider operation/interaction ID
    status: str = "prepared"         # prepared|dispatching|accepted|running|
                                     # succeeded|failed|unknown|downloaded
    outcome: dict = field(default_factory=dict)
    fallback_parent_attempt: str = ""
    reservation_id: str = ""

    def validate(self):
        e = super().validate()
        if self.attempt_seq < 1:
            e.append(ContractError("invalid_seq", "attempt_seq"))
        if self.provider and self.provider not in PROVIDERS:
            e.append(ContractError("unknown_provider", "provider",
                                   self.provider))
        return e


# ---------------------------------------------------------------- assets

@dataclass
class Artifact(Record):
    """Immutable accepted media. Revisions select artifacts; bytes never
    get overwritten."""
    sha256: str = ""
    kind: str = ""                   # video|audio|image|document
    byte_count: int = 0
    probe: dict = field(default_factory=dict)   # width/height/fps/frames/codec...
    provenance: str = ""
    provider_model: str = ""
    route: str = ""
    region: str = ""
    billing_scope: str = ""
    input_hashes: list = field(default_factory=list)
    native_audio: object = None      # None | {"present": bool, "policy": str}
    local_path: str = ""
    generation_receipt: str = ""     # artifact id of raw provider receipt
    native_width: int = 0
    native_height: int = 0
    native_fps_num: int = 0
    native_fps_den: int = 1

    def validate(self):
        e = super().validate()
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256 or ""):
            e.append(ContractError("bad_sha256", "sha256"))
        if self.kind not in ("video", "audio", "image", "document"):
            e.append(ContractError("bad_kind", "kind", self.kind))
        if self.provenance and self.provenance not in PROVENANCES:
            e.append(ContractError("bad_provenance", "provenance",
                                   self.provenance))
        if self.byte_count < 0:
            e.append(ContractError("bad_bytes", "byte_count"))
        return e


@dataclass
class AssetUse(Record):
    variant_id: str = ""
    segment_id: str = ""
    artifact_id: str = ""
    source: FrameInterval = None
    target: FrameInterval = None
    transforms: dict = field(default_factory=dict)

    def validate(self):
        e = super().validate()
        if not self.artifact_id:
            e.append(ContractError("missing_field", "artifact_id"))
        return e


# ---------------------------------------------------------------- review

@dataclass
class Review(Record):
    """Acceptance bound to an exact target hash; input change invalidates."""
    target_hash: str = ""            # artifact/composition hash reviewed
    check_type: str = ""             # technical|creative|changed_region|caption
    reviewer_type: str = ""          # human|automated|agent
    verdict: str = ""                # pass|fail|uncertain
    evidence_ids: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    invalidated_by: str = ""         # hash that superseded target_hash

    def validate(self):
        e = super().validate()
        if not re.fullmatch(r"[0-9a-f]{64}", self.target_hash or ""):
            e.append(ContractError("bad_target_hash", "target_hash"))
        if self.verdict not in ("", "pass", "fail", "uncertain"):
            e.append(ContractError("bad_verdict", "verdict", self.verdict))
        return e

    @property
    def stale(self):
        return bool(self.invalidated_by)


# -------------------------------------------------------------- delivery

@dataclass
class Delivery(Record):
    variant_plan_id: str = ""
    experiment_revision: int = 0
    file_sha256: str = ""
    drive_file_id: str = ""
    drive_link: str = ""
    remote_md5: str = ""
    verified_at: str = ""
    parent_folder_id: str = ""
    cleanup_receipt: str = ""
    status: str = "pending"          # pending|uploaded|verified|conflict

    def validate(self):
        e = super().validate()
        if self.status == "verified":
            if not self.drive_file_id or not self.remote_md5 \
                    or not self.verified_at:
                e.append(ContractError("unverified_delivery", "status",
                                       "verified requires id+md5+time"))
        if self.status not in ("pending", "uploaded", "verified",
                               "conflict", "failed"):
            e.append(ContractError("bad_delivery_status", "status",
                                   self.status))
        return e


# ------------------------------------------------------------ publishing

@dataclass
class Publication(Record):
    variant_plan_id: str = ""
    final_sha256: str = ""
    platform: str = ""
    account_id: str = ""
    request_id: str = ""
    remote_post_id: str = ""
    post_url: str = ""
    status: str = "requested"        # requested|uploading|scheduled|draft|
                                     # public|failed|unknown
    scheduled_at: str = ""
    published_at: str = ""           # actual public time, not ack time
    visibility: str = ""
    authorization_id: str = ""

    def validate(self):
        e = super().validate()
        states = {"requested", "uploading", "processing", "scheduled",
                  "draft", "public", "failed", "unknown"}
        if self.status not in states:
            e.append(ContractError("bad_publication_status", "status",
                                   self.status))
        if self.status == "public" and not self.published_at:
            e.append(ContractError("public_needs_time", "published_at"))
        return e


@dataclass
class MetricSnapshot(Record):
    """One pull of metrics for a publication. Missing ≠ zero."""
    publication_id: str = ""
    metric_definitions: dict = field(default_factory=dict)
    requested_period: dict = field(default_factory=dict)
    actual_coverage: dict = field(default_factory=dict)
    source: str = ""                 # data_api|analytics_api|reporting_api|manual
    observed_at: str = ""
    metrics: dict = field(default_factory=dict)   # name -> number|None
    completeness: str = "complete"   # complete|partial|pending|failed
    missing_reason: str = ""

    def validate(self):
        e = super().validate()
        if self.completeness not in ("complete", "partial", "pending",
                                     "failed"):
            e.append(ContractError("bad_completeness", "completeness"))
        return e


@dataclass
class Decision(Record):
    experiment_id: str = ""
    experiment_revision: int = 0
    policy_version: str = ""
    horizon: str = ""                # 48h|7d|28d
    primary_metric: str = ""
    comparisons: list = field(default_factory=list)  # B/C/D vs A results
    conclusion: str = ""             # waiting_for_data|insufficient_exposure|
                                     # inconclusive|provisional_winner|
                                     # no_improvement|needs_retest
    evidence_ids: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    superseded_by: str = ""

    CONCLUSIONS = ("waiting_for_data", "insufficient_exposure",
                   "inconclusive", "provisional_winner", "no_improvement",
                   "needs_retest")

    def validate(self):
        e = super().validate()
        if self.conclusion and self.conclusion not in self.CONCLUSIONS:
            e.append(ContractError("bad_conclusion", "conclusion",
                                   self.conclusion))
        return e


@dataclass
class DiscoveryRun(Record):
    """One research scan: plan, coverage, cohorts and ranked candidates.
    Every ratio recomputes from the stored inputs."""
    plan: dict = field(default_factory=dict)
    status: str = "running"          # running | complete | partial
    coverage: dict = field(default_factory=dict)   # planned vs received pages
    candidates: list = field(default_factory=list)
    cohort: dict = field(default_factory=dict)
    exported_seed_ids: list = field(default_factory=list)

    def validate(self):
        e = super().validate()
        if self.status not in ("running", "complete", "partial"):
            e.append(ContractError("bad_run_status", "status", self.status))
        return e
