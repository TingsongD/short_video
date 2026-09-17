"""F13 manual scenarios: template authoring from the haul blueprint,
validation of bad allocations, capability routing, revision pinning."""
import json
from pathlib import Path

from .cases_f01 import CaseContext, _result
from ..domain.clocks import FPS_30, FrameInterval
from ..domain.errors import ContractError
from ..domain.records import Beat, ReferenceBlueprint
from ..store import Database
from ..templates import (TemplateService, capability_report,
                         validate_template)


def _haul_blueprint():
    """Accepted 30 s haul blueprint: hook / 3 products / proof / cta."""
    spans = [(0, 120), (120, 240), (240, 360), (360, 510),
             (510, 780), (780, 900)]
    roles = ["hook", "product_reveal", "product_reveal",
             "product_reveal", "proof", "cta"]
    beats = [Beat(id=f"b{i}", role=r,
                  target=FrameInterval(s, e),
                  speech_segment_id=f"t{i}")
             for i, (r, (s, e)) in enumerate(zip(roles, spans))]
    return ReferenceBlueprint(
        schema_version="blueprint.v1", id="bp-haul", seed_id="seed-haul",
        created_at="2026-09-16T00:00:00Z", revision=1, status="accepted",
        clock=FPS_30, target_frames=900, beats=beats,
        speech={"transcript": [{"id": "t0",
                                "text": "Three outfits that fix Monday.",
                                "start_s": 0, "end_s": 4}]},
        content_hash="haul-bp-hash")


def f13_m01(ctx: CaseContext):
    """Template from the accepted haul blueprint; substitute synthetic
    product/copy — rhythm kept, source specifics not embedded."""
    db = Database(ctx.run_dir / "m01.db")
    ts = TemplateService(db)
    tpl = ts.author(_haul_blueprint(), "ft-haul")
    ctx.check("six_slots", len(tpl.slots) == 6)
    ctx.check("rhythm_kept",
              sum(s.frames for s in tpl.slots) == 900)
    ctx.check("product_refs_required",
              all(s.required_reference == "image"
                  for s in tpl.slots if s.kind == "product"))
    blob = json.dumps([s.content for s in tpl.slots])
    ctx.check("no_source_text",
              "Monday" not in blob and "denim" not in blob
              and "presenter" not in blob.lower())
    # synthetic substitution is the plan's job; template stays generic
    ctx.check("slots_are_generic",
              all("beat_role" in s.content for s in tpl.slots))
    return _result(ctx, "awaiting_manual_review",
                   "6 slots, 900-frame rhythm, image refs on product "
                   "slots; no seed names/copy/presenter embedded",
                   limitations=["human reads the preview view for "
                                "readability"])


def f13_m02(ctx: CaseContext):
    """Under-allocated slot + handle-less transition → validation names
    the offenders before generation."""
    db = Database(ctx.run_dir / "m02.db")
    ts = TemplateService(db)
    tpl = ts.author(_haul_blueprint(), "ft-haul")
    tpl.slots[1].frames = tpl.slots[1].min_frames - 10   # too short
    tpl.slots[2].transition_out = "crossfade"           # no handles
    problems = validate_template(tpl, total_frames=900)
    flags = {p["flag"]: p["detail"] for p in problems}
    ctx.check("short_slot_named",
              "under_min" in flags and "s-b1" in flags["under_min"])
    ctx.check("handles_named", "missing_handles" in flags)
    return _result(ctx, "passed",
                   "validation names s-b1 (under min) and s-b2 "
                   "(crossfade without handles) before any generation")


def f13_m03(ctx: CaseContext):
    """Static composition → ffmpeg_fast; animated overlay → hypit;
    unknown effect → named unsupported, never dropped."""
    db = Database(ctx.run_dir / "m03.db")
    ts = TemplateService(db)
    tpl = ts.author(_haul_blueprint(), "ft-haul")
    static_rep = capability_report(tpl.slots)
    ctx.check("static_fast_path", static_rep["preferred"] == "ffmpeg_fast")
    tpl.slots[1].effects = ["animated_overlay"]
    anim_rep = capability_report(tpl.slots)
    ctx.check("animated_hypit", anim_rep["preferred"] == "hypit")
    tpl.slots[0].effects = ["magic_portal"]
    bad = capability_report(tpl.slots)
    ctx.check("unsupported_named",
              bad["preferred"] == "unsupported" and
              bad["unsupported"][0]["effects"] == ["magic_portal"])
    return _result(ctx, "passed",
                   "capability report routes static→ffmpeg_fast, "
                   "animated→hypit, and names magic_portal unsupported")


def f13_m04(ctx: CaseContext):
    """Revise caption placement; a plan bound to rev1 keeps its
    appearance; migration is an explicit revision choice."""
    db = Database(ctx.run_dir / "m04.db")
    ts = TemplateService(db)
    ts.author(_haul_blueprint(), "ft-haul")
    def move(body):
        body["constraints"]["caption"]["region"] = "upper_third"
        return body
    ts.revise("ft-haul", move, reason="caption reposition")
    old = ts.get("ft-haul", revision=1)
    new = ts.get("ft-haul")
    ctx.check("old_appearance_kept",
              old.constraints["caption"]["region"] == "lower_third")
    ctx.check("new_revision_distinct",
              new.revision == 2 and
              new.constraints["caption"]["region"] == "upper_third")
    # a plan pinned at rev1 still resolves to rev1 — no silent swap
    ctx.check("pinned_plan_unaffected",
              ts.get("ft-haul", revision=1).revision == 1)
    return _result(ctx, "passed",
                   "caption move wrote revision 2; revision 1 remains "
                   "readable with the original lower-third placement")


def implementations():
    return {"F13-M01": f13_m01, "F13-M02": f13_m02,
            "F13-M03": f13_m03, "F13-M04": f13_m04}
