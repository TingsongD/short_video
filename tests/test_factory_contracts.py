"""F02 — contract validation, frame clocks, money, revisions, legacy
conversion. All offline."""
import copy
import os

import pytest

from modules.factory.contracts.v1 import SCHEMA_VERSIONS, check_version
from modules.factory.domain import (
    Artifact, AssetUse, ContractError, Decision, Delivery,
    ExperimentRevision, FrameInterval, GenerationRequest, Job,
    MetricObservation, Money, PriceAssessment, ProviderPolicy,
    RationalRate, ReferenceBlueprint, Beat, Seed, VariantPlan, accept,
    check_partition, check_revision_chain, convert_produced_video,
    map_provenance, revise,
)
from modules.factory.domain.to_legacy import convert_or_refuse

SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "schemas")
NOW = "2026-09-16T12:00:00Z"


def _clock():
    return RationalRate(30, 1)


def _beats(total, n, start=0):
    """n beats tiling [start, start+total) evenly-ish."""
    step = total // n
    beats = []
    cur = start
    for i in range(n):
        end = cur + step if i < n - 1 else start + total
        beats.append(Beat(id=f"b{i+1}", role="body",
                          source=FrameInterval(cur - start, end - start),
                          target=FrameInterval(cur, end)))
        cur = end
    return beats


def _blueprint(beats, target_frames, **kw):
    bp = ReferenceBlueprint(
        schema_version="reference_blueprint.v1",
        id=kw.pop("id", "bp:test-01"), created_at=NOW,
        seed_id=kw.pop("seed_id", "seed:test-01"),
        revision=kw.pop("revision", 1), clock=_clock(),
        target_frames=target_frames, beats=beats, **kw)
    return bp


def _accepted_blueprint():
    return accept(_blueprint(_beats(900, 6), 900))


# --------------------------------------------------------------- clocks

class TestFrameClock:
    def test_rational_rates(self):
        assert RationalRate(30000, 1001).fps == pytest.approx(29.97, abs=0.001)
        assert _clock().seconds_to_frames(30) == 900
        assert _clock().seconds_to_frames(169.7) == 5091

    def test_zero_denominator_rejected(self):
        with pytest.raises(ContractError) as e:
            RationalRate(30, 0)
        assert e.value.code == "invalid_frame_rate"
        with pytest.raises(ContractError):
            RationalRate(0, 1)

    def test_interval_end_exclusive(self):
        a, b = FrameInterval(0, 60), FrameInterval(60, 120)
        assert not a.overlaps(b) and a.adjacent(b)
        assert a.overlaps(FrameInterval(59, 61))
        assert FrameInterval(10, 20).contains(FrameInterval(12, 18))
        with pytest.raises(ContractError):
            FrameInterval(60, 60)

    def test_partition_detects_gap_and_overlap(self):
        codes = [e.code for e in check_partition(
            [FrameInterval(0, 10), FrameInterval(20, 30)], 30)]
        assert "frame_gap" in codes
        codes = [e.code for e in check_partition(
            [FrameInterval(0, 15), FrameInterval(10, 30)], 30)]
        assert "frame_overlap" in codes
        assert check_partition([FrameInterval(0, 30)], 30) == []

    def test_20_take_plan_validates(self):
        beats = _beats(5091, 20)
        bp = _blueprint(beats, 5091)
        assert bp.validate() == []
        assert sum(b.target.length for b in bp.beats) == 5091


# ---------------------------------------------------------------- money

class TestMoney:
    def test_micros_are_integers(self):
        m = Money("usd_micros", 409384)
        assert m.to_dict() == {"unit": "usd_micros", "amount": 409384}

    @pytest.mark.parametrize("bad", [0.5, float("nan"), float("inf"), "5"])
    def test_non_integer_rejected(self, bad):
        with pytest.raises(ContractError) as e:
            Money("usd_micros", bad)
        assert e.value.code == "money_not_integer"

    def test_negative_and_unit_mixing_rejected(self):
        with pytest.raises(ContractError):
            Money("usd_micros", -1)
        with pytest.raises(ContractError):
            Money("credits", 5)
        with pytest.raises(ContractError) as e:
            Money("usd_micros", 5) + Money("jimeng_credits", 5)
        assert e.value.code == "unit_mismatch"


# --------------------------------------------------------------- records

class TestRecords:
    def test_seed_requires_canonical_url_for_remote_platform(self):
        s = Seed(schema_version="seed.v1", id="seed:a", created_at=NOW,
                 platform="youtube")
        codes = [e.code for e in s.validate()]
        assert "missing_field" in codes

    def test_metric_observation_missing_is_not_zero(self):
        o = MetricObservation(
            schema_version="metric_observation.v1", id="mo:1",
            created_at=NOW, seed_id="seed:a", views=None,
            unknown_reason="api_scope_missing")
        assert o.validate() == []
        assert o.follower_multiple() is None
        bad = MetricObservation(
            schema_version="metric_observation.v1", id="mo:2",
            created_at=NOW, seed_id="seed:a", views=None)
        assert any(e.code == "unknown_needs_reason"
                   for e in bad.validate())

    def test_median_multiple_uses_cohort_not_provider_score(self):
        o = MetricObservation(
            schema_version="metric_observation.v1", id="mo:1",
            created_at=NOW, seed_id="seed:a", views=10000, followers=500,
            cohort_median_views=2000, provider_score=99)
        assert o.follower_multiple() == 20.0
        assert o.median_multiple() == 5.0

    def test_malformed_ids_rejected(self):
        s = Seed(schema_version="seed.v1", id="BAD ID!", created_at=NOW,
                 platform="local", evidence_status="metadata_only")
        assert any(e.code == "malformed_id" for e in s.validate())

    def test_blueprint_overlapping_beats_rejected(self):
        beats = _beats(900, 6)
        beats[2] = Beat(id="b3", role="body",
                        source=FrameInterval(100, 200),
                        target=FrameInterval(149, 300))
        bp = _blueprint(beats, 900)
        codes = [e.code for e in bp.validate()]
        assert "frame_overlap" in codes

    def test_generation_request_binding(self):
        g = GenerationRequest(
            schema_version="generation_request.v1", id="gr:1",
            created_at=NOW, provider="jimeng_canvas", model="m",
            route="canvas", prompt="p", requested_duration_s=8.0,
            required_usable_s=6.0)
        h = g.finalize_hash()
        g2 = copy.deepcopy(g)
        assert g2.finalize_hash() == h        # deterministic
        g2.provider = "google_vertex"
        assert g2.finalize_hash() != h        # provider is bound
        assert any(e.code == "usable_exceeds_requested"
                   for e in GenerationRequest(
                       schema_version="generation_request.v1", id="g:x",
                       created_at=NOW, requested_duration_s=4,
                       required_usable_s=5).validate())

    def test_price_assessment_kinds_and_units(self):
        p = PriceAssessment(
            schema_version="price_assessment.v1", id="pa:1", created_at=NOW,
            kind="usage_estimate", request_hash="x", unit="usd_micros",
            amount=409384, reserve_amount=500000)
        assert p.validate() == []
        bad = copy.deepcopy(p)
        bad.kind = "wild_guess"
        assert any(e.code == "unknown_price_kind" for e in bad.validate())

    def test_variant_plan_requires_declared_treatment(self):
        v = VariantPlan(
            schema_version="variant_plan.v1", id="vp:1", created_at=NOW,
            experiment_id="exp:1", variant_key="B", target_frames=900)
        codes = [e.code for e in v.validate()]
        assert "missing_field" in codes
        v.hypothesis = "stronger hook"
        v.changed_factor = "hook"
        v.allowed_regions = [FrameInterval(0, 90)]
        v.locked_fields = ["voice", "music", "cta"]
        assert v.validate() == []
        # region out of range
        v.allowed_regions = [FrameInterval(800, 1000)]
        assert any(e.code == "region_out_of_range" for e in v.validate())

    def test_job_state_enum(self):
        j = Job(schema_version="job.v1", id="j:1", created_at=NOW,
                logical_key="k", status="teleported")
        assert any(e.code == "bad_job_state" for e in j.validate())

    def test_artifact_sha_and_provenance(self):
        a = Artifact(schema_version="artifact.v1", id="a:1", created_at=NOW,
                     sha256="z" * 64, kind="video",
                     provenance="jimeng_canvas")
        assert any(e.code == "bad_sha256" for e in a.validate())
        a.sha256 = "a" * 64
        assert a.validate() == []
        a.provenance = "unknown_vendor"
        assert any(e.code == "bad_provenance" for e in a.validate())

    def test_delivery_verified_needs_evidence(self):
        d = Delivery(schema_version="delivery.v1", id="d:1", created_at=NOW,
                     status="verified")
        assert any(e.code == "unverified_delivery" for e in d.validate())

    def test_decision_conclusion_enum(self):
        d = Decision(schema_version="decision.v1", id="dc:1", created_at=NOW,
                     conclusion="feels_good")
        assert any(e.code == "bad_conclusion" for e in d.validate())

    def test_unknown_schema_version_refused(self):
        check_version("artifact.v1")
        with pytest.raises(ContractError):
            check_version("artifact.v99")


# ------------------------------------------------------------- revisions

class TestRevisions:
    def test_accept_freezes_hash(self):
        bp = _blueprint(_beats(900, 6), 900)
        accept(bp)
        assert bp.status == "accepted" and len(bp.content_hash) == 64
        with pytest.raises(ContractError):
            accept(bp)

    def test_revise_creates_child_with_parent(self):
        bp = _accepted_blueprint()
        child = revise(bp, "shorten hook", reason_ref="review:r1")
        assert bp.status == "superseded"
        assert child.revision == 2
        assert child.parent_hash == bp.content_hash
        assert child.status == "draft" and not child.content_hash
        assert child.revision_reason == "shorten hook"

    def test_revise_requires_reason(self):
        bp = _accepted_blueprint()
        with pytest.raises(ContractError) as e:
            revise(bp, "")
        assert e.value.code == "missing_revision_reason"

    def test_revision_chain_check(self):
        r1 = _accepted_blueprint()
        r2 = revise(r1, "change")
        accept(r2)
        assert check_revision_chain([r1, r2]) == []
        r3 = revise(r2, "again")
        r3.parent_hash = "0" * 64
        accept(r3)
        codes = [e.code for e in check_revision_chain([r1, r2, r3])]
        assert "parent_hash_mismatch" in codes


# ---------------------------------------------------------- legacy bridge

class TestLegacyConversion:
    def _artifact(self, i, provenance):
        return Artifact(
            schema_version="artifact.v1", id=f"a:{i}", created_at=NOW,
            sha256=f"{i:064d}", kind="video", provenance=provenance,
            local_path=f"clip{i}.mp4")

    def _uses(self, n, provenance="jimeng_canvas"):
        uses, arts = [], {}
        for i in range(n):
            a = self._artifact(i, provenance)
            arts[a.id] = a
            uses.append(AssetUse(schema_version="asset_use.v1",
                                 id=f"au:{i}", created_at=NOW,
                                 artifact_id=a.id,
                                 source=FrameInterval(i * 60, (i + 1) * 60)))
        return uses, arts

    def test_compatible_jimeng_converts_and_validates(self):
        uses, arts = self._uses(5)
        payload, report = convert_or_refuse(
            "vid1", uses, arts,
            os.path.join(SCHEMAS, "asset_manifest.schema.json"))
        assert payload["video_id"] == "vid1"
        assert len(payload["assets"]) == 5
        assert all(a["source"] == "jimeng" for a in payload["assets"])
        assert report.status_counts()["incompatible"] == 0

    def test_vertex_refuses_without_mislabeling(self):
        uses, arts = self._uses(5, "google_vertex")
        with pytest.raises(ContractError) as e:
            convert_or_refuse("vid1", uses, arts,
                              os.path.join(SCHEMAS,
                                           "asset_manifest.schema.json"))
        assert e.value.code == "legacy_conversion_refused"
        assert "mislabel" in str(e.value)

    def test_long_haul_shot_count_refused(self):
        uses, arts = self._uses(20)
        with pytest.raises(ContractError) as e:
            convert_or_refuse("vid1", uses, arts,
                              os.path.join(SCHEMAS,
                                           "asset_manifest.schema.json"))
        assert "shot_count" in str(e.value)

    def test_provenance_mapping_and_refusal(self):
        assert map_provenance("vertex") == "google_vertex"
        assert map_provenance("canvas") == "jimeng_canvas"
        with pytest.raises(ContractError):
            map_provenance("some_new_vendor")
        with pytest.raises(ContractError):
            map_provenance(None)

    def test_legacy_to_factory_report(self):
        r = convert_produced_video(
            {"id": "row7", "hook": "stop scrolling", "format": "pov",
             "provider": "vertex"})
        d = r.to_dict()
        assert d["fields"]["provenance"]["value"] == "google_vertex"
        assert d["fields"]["artifact_hash"]["status"] == "unresolved"
        r2 = convert_produced_video({"id": "row8", "provider": "mystery"})
        assert r2.fields["provenance"][0] == "unresolved"


# -------------------------------------------------------- F02 case impls

class TestF02Cases:
    def test_m01_frame_totals(self):
        six = _blueprint(_beats(900, 6), 900)
        twenty = _blueprint(_beats(5091, 20), 5091)
        assert six.validate() == [] and twenty.validate() == []
        assert sum(b.target.length for b in six.beats) == 900
        assert sum(b.target.length for b in twenty.beats) == 5091

    def test_m02_typed_errors(self):
        beats = _beats(900, 6)
        beats[1] = Beat(id="b2", role="body",
                        source=FrameInterval(60, 150),
                        target=FrameInterval(90, 300))   # overlap with b3
        errs = _blueprint(beats, 900).validate()
        assert any(e.field and "interval" in e.field for e in errs)
        a = Artifact(schema_version="artifact.v1", id="a:x",
                     created_at=NOW, sha256="a" * 64, kind="video",
                     provenance="made_up")
        assert any(e.field == "provenance" for e in a.validate())
