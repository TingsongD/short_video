"""Template validation (F13 automated checks): duration bounds,
required references/fonts, total coverage, transition handles,
unsupported effects, source-content leakage."""
from ..domain.errors import ContractError
from ..domain.clocks import check_partition, FrameInterval
from .capabilities import RENDERERS, capability_report


def validate_template(tpl, total_frames=None, available_fonts=None,
                      provided_references=None, source_strings=None):
    """→ list of {flag, detail} problems; empty means technically valid.
    `total_frames`: the plan clock the template must tile.
    `provided_references`: {"image": n, "video": n} counts the plan can
    supply. `source_strings`: seed-specific text that must not appear."""
    problems = []
    cursor, ivs = 0, []
    for s in tpl.slots:
        if s.min_frames <= 0 or s.frames <= 0:
            problems.append({"flag": "invalid_slot",
                             "detail": f"{s.id}: nonpositive duration"})
        if s.max_frames and s.max_frames < s.min_frames:
            problems.append({"flag": "invalid_slot",
                             "detail": f"{s.id}: max<min"})
        if s.frames < s.min_frames:
            problems.append({"flag": "under_min",
                             "detail": f"{s.id}: {s.frames} frames < "
                                       f"min {s.min_frames}"})
        if s.transition_out == "crossfade" and s.handle_frames <= 0:
            problems.append({"flag": "missing_handles",
                             "detail": f"{s.id}: crossfade needs "
                                       "handle_frames>0"})
        if s.transition_out not in RENDERERS["hypit"]["effects"] and \
                s.transition_out != "none":
            problems.append({"flag": "unsupported_effect",
                             "detail": f"{s.id}: transition "
                                       f"{s.transition_out}"})
        ivs.append(FrameInterval(cursor, cursor + s.frames))
        cursor += s.frames
    if total_frames:
        for e in check_partition(ivs, total_frames):
            problems.append({"flag": e.code, "detail": e.detail})
    cap = capability_report(tpl.slots, renderer_policy=tpl.constraints.get('renderer_policy'))
    for u in cap["unsupported"]:
        problems.append({"flag": "unsupported_effect",
                         "detail": f"{u['slot']}: {u['effects']}"})
    font = (tpl.constraints.get("caption") or {}).get("font")
    if font and available_fonts is not None and \
            font not in available_fonts:
        problems.append({"flag": "missing_font",
                         "detail": f"caption font {font!r} unavailable"})
    if provided_references is not None:
        need = {}
        for s in tpl.slots:
            if s.required_reference not in ("", "none"):
                need[s.required_reference] = \
                    need.get(s.required_reference, 0) + 1
        for kind, n in need.items():
            if provided_references.get(kind, 0) < n:
                problems.append({"flag": "missing_reference",
                                 "detail": f"needs {n} {kind} ref(s), "
                                           f"have "
                                           f"{provided_references.get(kind, 0)}"})
    if source_strings:
        haystack = " ".join(
            str(v) for s in tpl.slots for v in s.content.values())
        for t in source_strings:
            if t and t in haystack:
                problems.append({"flag": "source_leakage",
                                 "detail": f"source text embedded: "
                                           f"{t[:40]!r}"})
    return problems


def to_legacy_format(tpl):
    """Compatibility export to the frozen format_library shape — only
    possible when nothing richer than prose beats would be lost."""
    rich = []
    for s in tpl.slots:
        if s.effects or s.transition_out not in ("cut", "none") or \
                s.handle_frames:
            rich.append(s.id)
    if rich or (tpl.constraints or {}).get("caption", {}).get("font"):
        raise ContractError("legacy_export_lossy", "slots",
                            f"timed/effect structure on {rich or 'captions'} "
                            "cannot fit the legacy format")
    return {"format_id": tpl.id, "name": tpl.id,
            "hook_type": "onscreen",
            "beats": [s.content.get("beat_role", s.kind)
                      for s in tpl.slots],
            "cta_pattern": "see_cta_slot",
            "status": tpl.status,
            "our_stats": {"videos": 0, "wins": 0, "avg_multiplier": 0}}
