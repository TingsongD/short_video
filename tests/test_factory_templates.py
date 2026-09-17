"""F13 — reusable format and template authoring."""
import pytest

from modules.factory.domain.clocks import FPS_30, FrameInterval
from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import (
    Beat, FormatTemplate, ReferenceBlueprint, Slot)
from modules.factory.store import Database
from modules.factory.templates import (
    TemplateService, author_from_blueprint, capability_report,
    to_legacy_format, validate_template)


def _blueprint(status="accepted", beats=None, frames=900):
    beats = beats or [
        Beat(id="hook", role="hook",
             target=FrameInterval(0, 120), speech_segment_id="t1"),
        Beat(id="p1", role="product_reveal",
             target=FrameInterval(120, 360), speech_segment_id="t2"),
        Beat(id="p2", role="product_reveal",
             target=FrameInterval(360, 600), speech_segment_id="t3"),
        Beat(id="proof", role="proof",
             target=FrameInterval(600, 780), speech_segment_id="t4"),
        Beat(id="cta", role="cta",
             target=FrameInterval(780, 900), speech_segment_id="t5")]
    return ReferenceBlueprint(
        schema_version="blueprint.v1", id="bp-seed", seed_id="seed-x",
        created_at="2026-09-16T00:00:00Z", revision=1, status=status,
        clock=FPS_30, target_frames=frames, beats=beats,
        content_hash="bphash123")


@pytest.fixture
def svc(tmp_path):
    return TemplateService(Database(tmp_path / "f.db"))


class TestAuthoring:
    def test_structure_without_source_content(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        assert len(tpl.slots) == 5
        assert [s.kind for s in tpl.slots] == \
            ["hook", "product", "product", "proof", "cta"]
        assert tpl.status == "candidate"
        assert tpl.derived_from_blueprint == "bphash123"
        # timing derived, not copied text
        assert tpl.slots[1].frames == 240
        assert tpl.slots[1].min_frames == 120
        assert tpl.slots[1].max_frames == 360
        # product slots need a reference; hook doesn't
        assert tpl.slots[0].required_reference == "none"
        assert tpl.slots[1].required_reference == "image"
        # no transcript/source text anywhere in slot content
        blob = str([s.content for s in tpl.slots])
        assert "Monday" not in blob and "denim" not in blob

    def test_unaccepted_blueprint_refused(self, svc):
        with pytest.raises(ContractError) as e:
            svc.author(_blueprint(status="draft"), "ft-x")
        assert e.value.code == "blueprint_not_accepted"

    def test_long_haul_slot_count_preserved(self, svc):
        beats = [Beat(id=f"t{i}", role="product_reveal",
                      target=FrameInterval(i * 255, (i + 1) * 255))
                 for i in range(19)]
        beats.append(Beat(id="cta", role="cta",
                          target=FrameInterval(19 * 255, 5091)))
        tpl = svc.author(_blueprint(beats=beats, frames=5091), "ft-long")
        assert len(tpl.slots) == 20
        assert tpl.slots[-1].kind == "cta"


class TestValidation:
    def test_bounds_and_coverage(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        assert validate_template(tpl, total_frames=900) == []
        tpl.slots[0].min_frames = 0
        assert any(p["flag"] == "invalid_slot"
                   for p in validate_template(tpl, total_frames=900))
        tpl.slots[0].min_frames = 60
        tpl.slots[0].frames = 50           # now covers 830 of 900
        assert any(p["flag"] == "frame_coverage"
                   for p in validate_template(tpl, total_frames=900))

    def test_crossfade_needs_handles(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        tpl.slots[1].transition_out = "crossfade"
        flags = [p["flag"] for p in
                 validate_template(tpl, total_frames=900)]
        assert "missing_handles" in flags
        tpl.slots[1].handle_frames = 12
        assert not any(p["flag"] == "missing_handles"
                       for p in validate_template(tpl, total_frames=900))

    def test_required_reference_and_font(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        probs = validate_template(tpl, total_frames=900,
                                  provided_references={"image": 1})
        assert any(p["flag"] == "missing_reference" for p in probs)
        tpl.constraints["caption"]["font"] = "Inter-Bold"
        probs = validate_template(tpl, total_frames=900,
                                  provided_references={"image": 3},
                                  available_fonts=["DejaVu"])
        assert any(p["flag"] == "missing_font" for p in probs)

    def test_source_leakage_detected(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        tpl.slots[0].content["caption"] = "Three outfits that fix Monday."
        probs = validate_template(
            tpl, total_frames=900,
            source_strings=["Three outfits that fix Monday."])
        assert any(p["flag"] == "source_leakage" for p in probs)

    def test_unsupported_effect_named(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        tpl.slots[0].effects = ["particle_vortex"]
        probs = validate_template(tpl, total_frames=900)
        assert any("particle_vortex" in p["detail"] for p in probs)


class TestCapabilities:
    def test_static_routes_ffmpeg(self):
        slots = [Slot(id="s1", kind="product", frames=100,
                      effects=["static_image"], transition_out="cut")]
        rep = capability_report(slots)
        assert rep["preferred"] == "ffmpeg_fast"

    def test_animation_routes_hypit(self):
        slots = [Slot(id="s1", kind="product", frames=100,
                      effects=["animated_overlay"], transition_out="cut")]
        rep = capability_report(slots)
        assert rep["preferred"] == "hypit"
        assert rep["routes"]["s1"] == "hypit"

    def test_unknown_effect_unsupported(self):
        slots = [Slot(id="s1", kind="product", frames=100,
                      effects=["hologram"])]
        rep = capability_report(slots)
        assert rep["preferred"] == "unsupported"
        assert rep["unsupported"][0]["effects"] == ["hologram"]


class TestVersioning:
    def test_revise_keeps_old_revision(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        child = svc.revise("ft-haul", lambda b: b, reason="v2")
        assert child.revision == 2
        old = svc.get("ft-haul", revision=1)
        assert old.revision == 1 and old.slots[0].frames == 120

    def test_revision_changes_detection(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        def move_caption(body):
            body["constraints"]["caption"]["region"] = "top_third"
            return body
        child = svc.revise("ft-haul", move_caption, "caption reposition")
        assert child.constraints["caption"]["region"] == "top_third"
        # a plan bound to rev1 keeps rev1's appearance
        old = svc.get("ft-haul", revision=1)
        assert old.constraints["caption"]["region"] == "lower_third"

    def test_lifecycle_status(self, svc):
        svc.author(_blueprint(), "ft-haul")
        svc.set_status("ft-haul", "proven")
        assert svc.get("ft-haul").status == "proven"
        with pytest.raises(ContractError):
            svc.set_status("ft-haul", "viral")


class TestExport:
    def test_preview_and_view(self, svc):
        svc.author(_blueprint(), "ft-haul")
        out = svc.preview("ft-haul")
        assert out["spec"]["renderer"] == "ffmpeg_fast"
        assert "template ft-haul" in out["view"]
        assert "cta" in out["view"]

    def test_legacy_export_refuses_rich(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        tpl.constraints["caption"]["font"] = "Inter-Bold"
        with pytest.raises(ContractError) as e:
            to_legacy_format(tpl)
        assert e.value.code == "legacy_export_lossy"

    def test_legacy_export_flat_ok(self, svc):
        tpl = svc.author(_blueprint(), "ft-haul")
        for s in tpl.slots:
            s.effects = []
        out = to_legacy_format(tpl)
        assert out["format_id"] == "ft-haul"
        assert out["beats"] == ["hook", "product_reveal",
                                "product_reveal", "proof", "cta"]
