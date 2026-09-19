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
    # Round-N lineage (PL-01): a champion seed points at its parent and
    # the material family it belongs to. Empty = first-generation seed.
    parent_seed_id: str = ""
    lineage_root_id: str = ""        # original external reference seed
    round: int = 0                   # 0 = first round; 1+ = derived
    independence_group: str = ""     # root-material identity for
                                     # independent-experiment counting

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
    revision: int = 0                # catalog refresh => revision+1
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
    media_coverage: dict = field(default_factory=dict)  # {images, videos}
    warnings: list = field(default_factory=list)

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
    analysis: dict = field(default_factory=dict)   # {id, revision} stamped at accept
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
    frames: int = 0                  # nominal length at the template clock
    required_reference: str = ""     # image|video|none
    effects: list = field(default_factory=list)   # declarative effect names
    transition_out: str = "cut"      # cut | crossfade | none
    handle_frames: int = 0           # extra media a transition consumes
    content: dict = field(default_factory=dict)   # slot-local params


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
    revision: int = 1
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
    segments: list = field(default_factory=list)   # applied plan body
    dependent_fields: list = field(default_factory=list)  # transitive deps
    content_hash: str = ""
    stale_reason: str = ""

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
    plan_hash: str = ""              # plan revision this quote belongs to
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
    binding: dict = field(default_factory=dict)  # exact operation quotes, account, revision and budgets
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
            if p not in PROVIDERS | {"elevenlabs", "google_tts", "google_music", "generated_music", "viral_outliers", "drive", "upload_post", "analysis", "audiovisual_analysis", "youtube_reporting", "shopify"}:
                e.append(ContractError("unknown_provider",
                                       "allowed_providers", p))
        return e


# ------------------------------------------------------------ references

REFERENCE_ROLES = {"product_front", "product_back", "product_detail",
                   "presenter_headshot", "presenter_full", "style",
                   "scene"}
REFERENCE_ORIGINS = {"manual_import", "product_snapshot", "generated"}
ATTR_STATES = {"observed", "inferred", "unknown"}


@dataclass
class PresenterIdentity(Record):
    """Fictional or otherwise authorized presenter — never the seed's
    presenter copied forward."""
    kind: str = "fictional"          # fictional | licensed
    guide: dict = field(default_factory=dict)   # appearance/setting/
                                                # framing/wardrobe
    provenance: str = ""             # where the identity is authorized from

    def validate(self):
        e = super().validate()
        if self.kind not in ("fictional", "licensed"):
            e.append(ContractError("bad_presenter_kind", "kind", self.kind))
        if not self.provenance:
            e.append(ContractError("missing_field", "provenance"))
        if self.provenance == "seed_frame":
            e.append(ContractError("seed_presenter_copied", "provenance"))
        return e


@dataclass
class VisualReference(Record):
    """One candidate/accepted visual reference bound to exact artifact
    bytes. Acceptance pins `artifact_sha256`; a replaced reference is a
    new revision, never a mutation."""
    pack_id: str = ""
    revision: int = 0
    role: str = ""                   # REFERENCE_ROLES
    origin: str = "manual_import"    # REFERENCE_ORIGINS
    artifact_id: str = ""
    artifact_sha256: str = ""
    source_artifact_ids: list = field(default_factory=list)
    variant_id: str = ""
    attributes: dict = field(default_factory=dict)
    # {name: {"value": str, "state": observed|inferred|unknown}}
    acceptance: dict = field(default_factory=dict)
    # {state: pending|accepted|rejected, reviewer, reasons[], limits[],
    #  reviewed_hash}
    generation_attempt_id: str = ""
    parent_hash: str = ""
    status: str = "pending"          # pending|accepted|rejected|superseded

    def validate(self):
        e = super().validate()
        _id_errors(e, self.pack_id, "pack_id")
        if self.role not in REFERENCE_ROLES:
            e.append(ContractError("bad_reference_role", "role", self.role))
        if self.origin not in REFERENCE_ORIGINS:
            e.append(ContractError("bad_reference_origin", "origin",
                                   self.origin))
        for name, attr in (self.attributes or {}).items():
            if not isinstance(attr, dict):
                continue               # control keys: extra_details, ...
            if attr.get("state") not in ATTR_STATES:
                e.append(ContractError("bad_attr_state",
                                       f"attributes.{name}"))
        acc = self.acceptance or {}
        if acc.get("state") == "accepted" and \
                acc.get("reviewed_hash") != self.artifact_sha256:
            e.append(ContractError("acceptance_hash_mismatch",
                                   "acceptance.reviewed_hash"))
        if self.status not in ("pending", "accepted", "rejected",
                               "superseded"):
            e.append(ContractError("bad_reference_status", "status",
                                   self.status))
        return e


@dataclass
class ReferencePack(Record):
    """All visual references for one product/variant + presenter, bound
    to a plan hash. `pack_hash` identifies the accepted selection."""
    product_snapshot_id: str = ""
    product_id: str = ""
    variant_id: str = ""
    presenter_id: str = ""
    plan_hash: str = ""              # bound experiment/plan revision
    pack_hash: str = ""              # hash of {role: artifact_sha256}
    required_roles: list = field(default_factory=list)
    repair_attempts: int = 0
    status: str = "assembling"       # assembling|ready|stale

    def validate(self):
        e = super().validate()
        _id_errors(e, self.product_id, "product_id")
        if self.status not in ("assembling", "ready", "stale"):
            e.append(ContractError("bad_pack_status", "status", self.status))
        return e


# --------------------------------------------------------------- speech

@dataclass
class SpeechSegment(Record):
    """One narration segment. Identity = voice+model+language+settings+
    normalization+text → `cache_key` shared across variants; a changed
    hook is a different key, never a reread of the track."""
    segment_id: str = ""
    variant_id: str = ""
    cache_key: str = ""
    voice: dict = field(default_factory=dict)
    # {voice_id, model, language, settings{}}
    normalization: str = ""          # e.g. voicetext.v1
    source_text: str = ""            # as authored
    text: str = ""                   # normalized spoken text
    target: FrameInterval = None
    status: str = "planned"          # planned|submitted|voiced|aligned|
                                     # fitted|approved|failed|stale
    artifact_id: str = ""
    audio_sha256: str = ""
    duration_s: object = None        # measured; None while unknown
    fit: dict = field(default_factory=dict)
    speech_hash: str = ""            # approved version — lip-sync binds

    def validate(self):
        e = super().validate()
        _id_errors(e, self.segment_id, "segment_id")
        if self.status == "approved" and not self.speech_hash:
            e.append(ContractError("missing_field", "speech_hash"))
        if self.duration_s is not None and self.duration_s < 0:
            e.append(ContractError("bad_duration", "duration_s"))
        return e


@dataclass
class WordAlignment(Record):
    """Word timings measured against the exact returned waveform."""
    segment_id: str = ""
    audio_sha256: str = ""
    spoken_text: str = ""
    words: list = field(default_factory=list)
    # [{w, start_s, end_s, confidence}]
    aligner: dict = field(default_factory=dict)   # {kind, version}
    confidence: float = 0.0

    def validate(self):
        e = super().validate()
        _id_errors(e, self.segment_id, "segment_id")
        prev = -1.0
        for w in self.words:
            if w.get("start_s", 0) < prev or \
                    w.get("end_s", 0) < w.get("start_s", 0):
                e.append(ContractError("word_times_not_monotonic",
                                       "words", str(w)[:60]))
                break
            prev = w["end_s"]
        return e


@dataclass
class CaptionSet(Record):
    """Captions derived from the approved wording + alignment, mapped
    onto target frames after fit transforms."""
    segment_id: str = ""
    speech_hash: str = ""            # approved speech version bound
    cues: list = field(default_factory=list)
    # [{start_frame, end_frame, text, word_refs[]}]
    transform: dict = field(default_factory=dict)

    def validate(self):
        e = super().validate()
        _id_errors(e, self.segment_id, "segment_id")
        for c in self.cues:
            if c.get("end_frame", 0) <= c.get("start_frame", 0):
                e.append(ContractError("bad_cue", "cues", str(c)[:60]))
        return e


# ---------------------------------------------------------------- music

@dataclass
class MusicBed(Record):
    """One music master for an experiment — imported/licensed or
    generated. Provenance is mandatory; `bpm` stays None when
    unmeasured."""
    source: str = "imported"         # imported | generated
    provenance: str = ""             # license ref or model+route
    artifact_id: str = ""
    sha256: str = ""
    duration_s: object = None
    bpm: object = None
    structure: dict = field(default_factory=dict)
    brief: dict = field(default_factory=dict)   # seed energy/rhythm/
                                                # arrangement → original
    construction: dict = field(default_factory=dict)  # trims/loops/
                                                      # crossfades
    generation_attempt_id: str = ""
    status: str = "draft"            # draft | master | superseded

    def validate(self):
        e = super().validate()
        if self.source not in ("imported", "generated"):
            e.append(ContractError("bad_bed_source", "source",
                                   self.source))
        if not self.provenance:
            e.append(ContractError("missing_field", "provenance"))
        return e


@dataclass
class MixProfile(Record):
    """Frozen mix config for an experiment revision: bed, gains, duck
    envelope, rate/channels, clipping policy, measured loudness
    target. `profile_hash` is the frozen identity."""
    experiment_id: str = ""
    music_bed_id: str = ""
    sample_rate: int = 48000
    channels: int = 2
    speech_gain_db: float = 0.0
    music_gain_db: float = -14.0
    duck: dict = field(default_factory=dict)
    # {enabled, amount_db, regions: [FrameInterval-dict]}
    loudness_target: dict = field(default_factory=dict)
    # measured during fixture qualification — never an invented
    # platform number: {"rms_dbfs": x, "peak_dbfs": y, "basis": str}
    clip_policy: str = "prevent"     # prevent | allow_report
    profile_hash: str = ""
    status: str = "draft"            # draft | frozen

    def validate(self):
        e = super().validate()
        _id_errors(e, self.experiment_id, "experiment_id")
        if self.sample_rate <= 0 or self.channels not in (1, 2):
            e.append(ContractError("bad_mix_format", "sample_rate/"
                                   "channels"))
        if self.clip_policy not in ("prevent", "allow_report"):
            e.append(ContractError("bad_clip_policy", "clip_policy"))
        if self.status == "frozen" and not self.profile_hash:
            e.append(ContractError("missing_field", "profile_hash"))
        return e


@dataclass
class SoundEffect(Record):
    """Optional timed asset — changes require declared treatment scope;
    it must not leak into unchanged comparison regions."""
    experiment_id: str = ""
    variant_id: str = ""
    artifact_id: str = ""
    target: FrameInterval = None
    gain_db: float = 0.0
    treatment_scope: str = ""        # declared region key it belongs to

    def validate(self):
        e = super().validate()
        _id_errors(e, self.experiment_id, "experiment_id")
        if self.target is None:
            e.append(ContractError("missing_field", "target"))
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
    binding: dict = field(default_factory=dict)  # exact plan/composition/artifact
    reviewer: str = ""
    evidence_data: dict = field(default_factory=dict)

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
    artifact_id: str = ""
    variant_plan_id: str = ""
    final_sha256: str = ""
    platform: str = ""
    account_id: str = ""
    request_id: str = ""
    job_id: str = ""
    remote_post_id: str = ""
    post_url: str = ""
    status: str = "requested"        # requested|uploading|scheduled|draft|
                                     # public|failed|unknown
    scheduled_at: str = ""
    published_at: str = ""           # actual public time, not ack time
    visibility: str = ""
    authorization_id: str = ""
    idempotency_key: str = ""        # stable identity across retries
    metadata: dict = field(default_factory=dict)   # title/caption/tags
    media_url: str = ""              # accessible URL alternative to bytes
    timezone: str = "UTC"            # cadence + schedule timezone
    horizon_policy: dict = field(default_factory=dict)  # predeclared
    manual: bool = False             # manual lane registration
    deleted_at: str = ""             # explicit deletion — never silent
    experiment_id: str = ""          # owning experiment (resolved from variant plan)
    experiment_revision: int = 0     # revision at publication time — learning is scoped by it
    # Multi-destination + provider fields (PL-01). Defaults preserve
    # the legacy single-route Upload-Post behavior.
    provider: str = "upload_post"    # upload_post|blotato|treg|manual
    connection_id: str = ""          # connections.json publish.accounts id
    metadata_package_id: str = ""    # frozen MetadataPackage binding
    metadata_revision: int = 0
    remote_schedule_id: str = ""     # provider scheduled-job id (for cancel)

    def validate(self):
        e = super().validate()
        states = {"requested", "uploading", "processing", "scheduled",
                  "draft", "public", "failed", "unknown", "unverified",
                  "cancel_requested", "cancelled"}
        if self.status not in states:
            e.append(ContractError("bad_publication_status", "status",
                                   self.status))
        if self.status == "public" and not self.published_at:
            e.append(ContractError("public_needs_time", "published_at"))
        if not self.platform:
            e.append(ContractError("missing_field", "platform"))
        if not self.account_id:
            e.append(ContractError("missing_field", "account_id"))
        return e


@dataclass
class MetricSnapshot(Record):
    """One pull of metrics for a publication. Missing ≠ zero."""
    revision: int = 0
    publication_id: str = ""
    post_id: str = ""                # platform post pulled
    horizon: str = ""                # 48h|7d|28d|manual|<custom>
    query_version: str = ""
    timezone: str = "UTC"
    metric_definitions: dict = field(default_factory=dict)
    requested_period: dict = field(default_factory=dict)
    actual_coverage: dict = field(default_factory=dict)
    source: str = ""                 # data_api|analytics_api|reporting_api|manual
    observed_at: str = ""
    metrics: dict = field(default_factory=dict)   # name -> number|None
    availability: dict = field(default_factory=dict)  # name -> reason
    raw: dict = field(default_factory=dict)       # untouched responses
    attempts: int = 1                # retries reuse this snapshot
    completeness: str = "complete"   # complete|partial|pending|failed
    missing_reason: str = ""

    def validate(self):
        e = super().validate()
        if self.completeness not in ("complete", "partial", "pending",
                                     "failed"):
            e.append(ContractError("bad_completeness", "completeness"))
        return e


@dataclass
class DecisionPolicy(Record):
    """Frozen BEFORE publication: what evidence could change our mind.
    Immutable once bound — a revision is a new record, not an edit."""
    experiment_id: str = ""
    experiment_revision: int = 0
    policy_version: str = ""
    primary_metric: str = ""
    horizon: str = ""                # 48h|7d|28d
    exposure_metric: str = "thumbnail_impressions"
    min_exposure: int = 0
    practical_lift: float = 0.0      # minimum meaningful relative lift
    guardrails: dict = field(default_factory=dict)  # metric -> min
    comparison_rule: str = "any"     # any|all treatments vs control
    promote_min_independent_experiments: int = 2
    status: str = "frozen"           # frozen|revised
    content_hash: str = ""
    # Cross-platform seed-selection policy (PL-01), frozen in the same
    # call. Absent = legacy single-platform decide only.
    # {mode: primary_platform|weighted_rank, primary_platform, weights,
    #  min_margin, improvement_rule{kind,params}, provisional_horizon,
    #  mature_horizon, per_platform{platform:{primary_metric,
    #  min_exposure, guardrails}}}
    seed_policy: dict = field(default_factory=dict)

    def validate(self):
        e = super().validate()
        if self.status == "frozen":
            for f in ("primary_metric", "horizon", "policy_version"):
                if not getattr(self, f):
                    e.append(ContractError("missing_field", f))
            import math
            if type(self.min_exposure) is not int or self.min_exposure < 0 or type(self.practical_lift) not in (int,float) or not math.isfinite(self.practical_lift) or self.practical_lift < 0:
                e.append(ContractError("invalid_policy_value",
                                       "min_exposure|practical_lift"))
            if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in self.guardrails.values()):e.append(ContractError('invalid_guardrail','guardrails'))
        return e


@dataclass
class Decision(Record):
    experiment_id: str = ""
    experiment_revision: int = 0
    policy_version: str = ""
    horizon: str = ""                # 48h|7d|28d|24h|72h|7d_complete|...
    platform: str = ""               # '' legacy/all | youtube|tiktok|
                                     # instagram|facebook (per-platform
                                     # decisions, PL-05)
    primary_metric: str = ""
    comparisons: list = field(default_factory=list)  # B/C/D vs A results
    conclusion: str = ""             # see CONCLUSIONS
    winner: str = ""                 # variant key when provisional_winner
    evidence_ids: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    inputs_hash: str = ""            # identical inputs → identical decision
    superseded_by: str = ""

    CONCLUSIONS = ("waiting_for_data", "insufficient_exposure",
                   "inconclusive", "provisional_winner", "no_improvement",
                   "needs_retest", "retain_control", "invalid_comparison",
                   "confirmed_winner")

    def validate(self):
        e = super().validate()
        if self.conclusion and self.conclusion not in self.CONCLUSIONS:
            e.append(ContractError("bad_conclusion", "conclusion",
                                   self.conclusion))
        return e


@dataclass
class Hypothesis(Record):
    """A searchable lesson: claim + evidence + uncertainty. Accepted
    lessons inform recommendations; they never silently rewrite
    generation defaults."""
    claim: str = ""
    evidence_ids: list = field(default_factory=list)
    uncertainty: str = "medium"      # low|medium|high
    limitations: list = field(default_factory=list)
    status: str = "candidate"        # candidate|accepted|retired
    source: str = ""                 # decision:<id> | operator:<name>
    attributed_to: str = ""          # operator name for overrides

    def validate(self):
        e = super().validate()
        if self.uncertainty not in ("low", "medium", "high"):
            e.append(ContractError("bad_uncertainty", "uncertainty",
                                   self.uncertainty))
        if self.status not in ("candidate", "accepted", "retired"):
            e.append(ContractError("bad_hypothesis_status", "status",
                                   self.status))
        return e


# ------------------------------------------------------------------
# Publishing & learning loop records (PL-01). Additive kinds; all new
# fields have defaults so older bodies deserialize unchanged.

PUBLISH_PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")


@dataclass
class MetadataPackage(Record):
    """Versioned publish-metadata package for one variant on one
    platform (PL-02). Candidates are generated from accepted creative
    evidence; the selected set is frozen before publication planning."""
    variant_plan_id: str = ""
    final_sha256: str = ""
    platform: str = ""               # youtube|tiktok|instagram|facebook
    revision: int = 0
    status: str = "draft"            # draft|frozen|superseded
    candidates: list = field(default_factory=list)   # [{id,via,fields,notes}]
    selected: dict = field(default_factory=dict)     # chosen platform fields
    disclosures: dict = field(default_factory=dict)  # ai_content|branded|audience
    generator: dict = field(default_factory=dict)    # {route,model,prompt_version,evidence_id}
    validation: dict = field(default_factory=dict)   # {ok,errors[],checked_fields[]}
    content_hash: str = ""

    def validate(self):
        e = super().validate()
        if self.platform and self.platform not in PUBLISH_PLATFORMS:
            e.append(ContractError("unsupported_platform", "platform",
                                   self.platform))
        if self.status not in ("draft", "frozen", "superseded"):
            e.append(ContractError("bad_metadata_status", "status",
                                   self.status))
        if self.status == "frozen" and not self.selected:
            e.append(ContractError("frozen_needs_selection", "selected"))
        return e


@dataclass
class SeedSelection(Record):
    """One seed-selection evaluation for an experiment revision at one
    checkpoint (PL-05). Evaluation is separate from child creation;
    a revision chain (`-v{N}`) records mature reevaluation."""
    experiment_id: str = ""
    experiment_revision: int = 0
    horizon: str = ""                # 24h|48h|72h|7d|7d_complete|28d|...
    status: str = "waiting"          # waiting|provisional|confirmed|
                                     # revised|inconclusive|superseded
    winner_variant: str = ""         # A|B|C|D — A is a legal winner
    publication_id: str = ""         # winning variant's evidence post
    artifact_id: str = ""            # winning ORIGINAL master artifact
    basis: dict = field(default_factory=dict)        # per-platform ranks,
                                                     # scores, policy hash
    decision_ids: list = field(default_factory=list) # per-platform decisions
    inputs_hash: str = ""            # identical inputs → identical evaluation
    seed_id: str = ""                # created Round-2 seed (set on transition)
    limitations: list = field(default_factory=list)
    superseded_by: str = ""

    def validate(self):
        e = super().validate()
        if self.status not in ("waiting", "provisional", "confirmed",
                               "revised", "inconclusive", "superseded"):
            e.append(ContractError("bad_selection_status", "status",
                                   self.status))
        if self.winner_variant and self.winner_variant not in VARIANT_KEYS:
            e.append(ContractError("bad_winner", "winner_variant",
                                   self.winner_variant))
        return e


@dataclass
class CheckpointSchedule(Record):
    """Durable due-entry for one metric observation of one publication
    (PL-04). One logical schedule per (publication, horizon); immutable
    MetricSnapshot revisions attach evidence to it."""
    publication_id: str = ""
    horizon: str = ""
    due_at: str = ""                 # UTC instant the collection becomes due
    window_kind: str = ""            # observed_lifetime_at_age|
                                     # source_calendar_window|exact_elapsed_window
    status: str = "pending"          # pending|due|collected|missed|late|failed
    attempts: int = 0
    next_attempt_at: str = ""
    job_id: str = ""                 # enqueued readback job when due
    query_version: str = ""
    policy_ref: str = ""

    def validate(self):
        e = super().validate()
        if self.status not in ("pending", "due", "collected", "missed",
                               "late", "failed"):
            e.append(ContractError("bad_checkpoint_status", "status",
                                   self.status))
        if self.status in ("due", "collected", "late") and not self.due_at:
            e.append(ContractError("checkpoint_needs_due_at", "due_at"))
        return e


@dataclass
class RoundLineage(Record):
    """One Round-N child: series, parent experiment and the selection
    that produced the new seed (PL-06). The independence group survives
    across derived rounds so related material is never double-counted."""
    series_id: str = ""
    round: int = 0
    parent_experiment_id: str = ""
    parent_experiment_revision: int = 0
    parent_selection_id: str = ""    # SeedSelection that justified the child
    seed_id: str = ""                # created Round-N seed
    experiment_id: str = ""          # created Round-N experiment (once run)
    root_reference_id: str = ""      # ORIGINAL external reference seed
    independence_group: str = ""
    status: str = "proposed"         # proposed|active|superseded|cancelled

    def validate(self):
        e = super().validate()
        if self.status not in ("proposed", "active", "superseded",
                               "cancelled"):
            e.append(ContractError("bad_lineage_status", "status",
                                   self.status))
        return e


@dataclass
class LoopPolicy(Record):
    """Bounded continuation authority for a series (PL-06).
    propose_only = a reviewable next-round proposal; execute_within_
    authorization = the funded, scoped policy may continue without
    repeated prompts, never beyond its recorded scope."""
    series_id: str = ""
    mode: str = "propose_only"       # propose_only|execute_within_authorization
    max_rounds: int = 0              # 0 = unbounded is NOT allowed; >0 required
    max_posts: int = 0
    allowed_providers: list = field(default_factory=list)
    allowed_accounts: list = field(default_factory=list)
    spend_caps: dict = field(default_factory=dict)   # unit -> max
    valid_until: str = ""
    stop_conditions: list = field(default_factory=list)
    status: str = "active"           # active|paused|revoked|expired
    authorization_id: str = ""       # funding authorization when executing

    def validate(self):
        e = super().validate()
        if self.mode not in ("propose_only", "execute_within_authorization"):
            e.append(ContractError("bad_loop_mode", "mode", self.mode))
        if self.status not in ("active", "paused", "revoked", "expired"):
            e.append(ContractError("bad_loop_status", "status",
                                   self.status))
        if self.mode == "execute_within_authorization" and not self.authorization_id:
            e.append(ContractError("execution_needs_authorization",
                                   "authorization_id"))
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


# ------------------------------------------------------------ production

WORK_KINDS = {"picture", "download", "review", "compose", "deliver"}
WORK_STATES = {"planned", "blocked", "ready", "submitted", "downloaded",
               "reviewing", "accepted", "rejected", "uncertain",
               "manual", "needs_manual", "done", "failed"}


@dataclass
class WorkItem(Record):
    """One unique node in the production graph. Shared work carries all
    consuming takes; per-variant work carries exactly one."""
    revision: int = 0
    plan_id: str = ""
    kind: str = ""                   # picture|download|review|compose|deliver
    node_key: str = ""               # stable key inside the plan
    request_hash: str = ""           # canonical dedupe key (picture)
    takes: list = field(default_factory=list)     # [{variant,slot,duration_s}]
    consumers: list = field(default_factory=list)  # variant keys downstream
    allocations: list = field(default_factory=list)
    # [{duration_s, offset_s, split}] provider-duration fitting
    provider: str = ""
    model: str = ""
    request: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)    # ref/speech/artifact hashes
    price: dict = field(default_factory=dict)     # {unit, amount}
    status: str = "planned"
    depends: list = field(default_factory=list)   # node_keys
    artifact_ids: list = field(default_factory=list)
    operation_id: str = ""
    problem: str = ""

    def validate(self):
        e = super().validate()
        _id_errors(e, self.plan_id, "plan_id")
        if self.kind not in WORK_KINDS:
            e.append(ContractError("unknown_work_kind", "kind", self.kind))
        if self.status not in WORK_STATES:
            e.append(ContractError("unknown_work_status", "status",
                                   self.status))
        return e


@dataclass
class ProductionPlan(Record):
    """Priced unique-work DAG for one accepted experiment revision."""
    experiment_id: str = ""
    experiment_revision: int = 0
    revision: int = 0
    status: str = "draft"            # draft|active|halted|complete
    plan_hash: str = ""
    stats: dict = field(default_factory=dict)
    # {takes, unique_pictures, shared_pictures, splits, manual_needed}
    total_price: dict = field(default_factory=dict)   # {unit: micros}
    variants: list = field(default_factory=list)
    stale_reason: str = ""

    def validate(self):
        e = super().validate()
        _id_errors(e, self.experiment_id, "experiment_id")
        if self.status not in ("draft", "active", "halted", "complete"):
            e.append(ContractError("unknown_plan_status", "status",
                                   self.status))
        return e


# ------------------------------------------------------------ composition

@dataclass
class Composition(Record):
    """One compiled variant composition: SVML/SVS/SVRun + binding
    manifest, deterministic for identical inputs."""
    experiment_id: str = ""
    variant_key: str = ""
    revision: int = 0
    parent_revision: int = 0
    parent_hash: str = ""
    plan_id: str = ""
    status: str = "draft"            # draft | checked | failed
    renderer: str = "hypit"          # hypit | ffmpeg_fast
    clock: dict = field(default_factory=dict)   # {fps,width,height}
    total_frames: int = 0
    files: dict = field(default_factory=dict)
    # {"svml": sha, "svs": sha, "svrun": sha, "manifest": sha}
    bindings: list = field(default_factory=list)
    # [{binding, role, artifact_id, sha256, in_frame, out_frame}]
    source_revisions: dict = field(default_factory=dict)
    content_hash: str = ""
    diagnostics: list = field(default_factory=list)

    def validate(self):
        e = super().validate()
        _id_errors(e, self.experiment_id, "experiment_id")
        if self.variant_key not in VARIANT_KEYS:
            e.append(ContractError("bad_variant", "variant_key",
                                   self.variant_key))
        if self.renderer not in ("hypit", "ffmpeg_fast"):
            e.append(ContractError("unknown_renderer", "renderer",
                                   self.renderer))
        return e


# ------------------------------------------------------------ rendering

RENDER_STATES = {"registered", "running", "succeeded", "failed",
                 "observer_lost", "collected"}


@dataclass
class RenderBuild(Record):
    """An owned render execution registered before it runs."""
    revision: int = 0
    composition_id: str = ""
    composition_hash: str = ""
    variant_key: str = ""
    renderer: str = ""               # ffmpeg_fast | hypit
    renderer_version: str = ""
    workspace: str = ""
    output_name: str = "final.video"
    status: str = "registered"
    remote_build_id: str = ""        # hypit build id (ours = id)
    inputs_hash: str = ""
    output_artifact_id: str = ""
    output_sha256: str = ""
    progress: dict = field(default_factory=dict)
    # {completed_sections: [...], current, updated_at}
    problem: str = ""
    finished_at: str = ""

    def validate(self):
        e = super().validate()
        _id_errors(e, self.composition_id, "composition_id")
        if self.status not in RENDER_STATES:
            e.append(ContractError("bad_render_state", "status",
                                   self.status))
        if self.renderer not in ("ffmpeg_fast", "hypit"):
            e.append(ContractError("unknown_renderer", "renderer",
                                   self.renderer))
        return e


# ------------------------------------------------- reference analysis

ANALYSIS_STATES = {"in_progress", "evidence_ready", "awaiting_review",
                   "complete", "blocked", "superseded"}


@dataclass
class ReferenceAnalysis(Record):
    """Mandatory deep-analysis work product for a seed's source media
    (Hypit-directed reference understanding). Machine evidence stages
    produce verifiable artifacts; operator stages supply the semantic
    reading and creative answer; a human review completes it. Approval
    elsewhere binds (source_sha256, analysis id+revision) exactly."""
    seed_id: str = ""
    revision: int = 0
    status: str = "in_progress"      # see ANALYSIS_STATES
    stage: str = ""                  # current/last machine stage
    stages: dict = field(default_factory=dict)  # per-stage checkpoints
    source_asset_id: str = ""
    source_sha256: str = ""
    acquisition: dict = field(default_factory=dict)
    # {url, artifact_id, sha256, duration_s, width, height, fps,
    #  audio_present, via, verified_at}
    capabilities: dict = field(default_factory=dict)
    # {hypit: bool, whisperx: bool, transcript_import: True}
    transcript: dict = field(default_factory=dict)
    # {status: aligned|unavailable|preliminary|not_applicable|
    #  declared_nonverbal, provider, confidence, provenance,
    #  word_count, file, preliminary: bool}
    evidence: dict = field(default_factory=dict)
    # {boundaries: [{t,score}], grids: [{artifact_id,start_s,end_s,
    #  every_s,transcript_linked}], coverage_s}
    understanding: dict = field(default_factory=dict)
    # premise, progression, hook, setups, payoffs, ending,
    # replay_appeal, intended_response, observations[],
    # interpretations[], uncertainties[]
    timeline: list = field(default_factory=list)
    # [{start_s,end_s,phase,summary,evidence_ids}]
    treatment: dict = field(default_factory=dict)
    # summary, preserves, redesigns, script_direction, prompt_notes
    documents: dict = field(default_factory=dict)
    # {root, files: {analysis_md,timeline_md,brief_md,treatment_md,
    #  progress_md,transcript_json}, hashes}
    review: dict = field(default_factory=dict)
    blocking: list = field(default_factory=list)
    # [{code, detail, recovery}]
    content_hash: str = ""

    def validate(self):
        e = super().validate()
        _id_errors(e, self.seed_id, "seed_id")
        if self.status not in ANALYSIS_STATES:
            e.append(ContractError("bad_analysis_status", "status",
                                   self.status))
        return e
