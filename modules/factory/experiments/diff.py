"""Semantic + timing diff between a control plan and a branch
(F14 checklist 3, 5). A branch may only differ inside its declared
frame regions and declared fields; anything else is a policy breach —
music, product, voice or provider drift is named explicitly.
"""
from ..domain.clocks import FrameInterval

DEPENDENT_OF = {
    # changing a segment's copy forces its derived tracks to change too;
    # those must live inside the same declared region
    "copy": ["speech", "captions", "picture"],
    "speech": ["captions", "picture"],
}
LOCKABLE = {"products", "presenter", "voice", "music",
            "provider_policy", "template_ref", "target_frames"}


def to_interval(r):
    """FrameInterval from either wire shape: dataclass {start,end} or
    serialized {start_frame,end_frame}."""
    if isinstance(r, FrameInterval):
        return r
    if "start_frame" in r:
        return FrameInterval.from_dict(r)
    return FrameInterval(r["start"], r["end"])


def _seg_frames(seg):
    return to_interval(seg.get("target") or {})


def _inside(iv, regions):
    return any(r.contains(iv) for r in regions)


def diff_plans(control_segments, variant_segments):
    """→ {"fields": {...}, "regions": [FrameInterval]} of every
    difference, for review — not for enforcement."""
    changed_fields, regions = set(), []
    for c, v in zip(control_segments, variant_segments):
        for k in set(c) | set(v):
            if c.get(k) != v.get(k):
                changed_fields.add(k)
                regions.append({"segment": c.get("id"),
                                "field": k,
                                "target": v.get("target")})
    return {"changed_fields": sorted(changed_fields),
            "regions": regions}


def check_treatment(control, variant, allowed_regions, allowed_fields,
                    locked_fields):
    """→ list of problems. One declared change; everything else locked."""
    problems = []
    regions = [to_interval(r) for r in allowed_regions]
    csegs = control["segments"]
    vsegs = variant["segments"]
    if len(csegs) != len(vsegs):
        problems.append({"flag": "segment_count_mismatch",
                         "detail": "branch must keep A's segmentation"})
        return problems
    for c, v in zip(csegs, vsegs):
        for k in set(c) | set(v):
            if c.get(k) == v.get(k):
                continue
            iv = _seg_frames(v)
            if not _inside(iv, regions):
                problems.append({
                    "flag": "change_outside_region",
                    "detail": f"segment {c.get('id')} field {k} changed "
                              f"at {iv.start}-{iv.end} outside declared "
                              "regions"})
            if k not in allowed_fields:
                problems.append({
                    "flag": "undeclared_field",
                    "detail": f"segment {c.get('id')} field {k} not in "
                              "allowed_fields"})
    for k in set(control) | set(variant):
        if k == "segments" or control.get(k) == variant.get(k):
            continue
        if k in LOCKABLE or k in locked_fields:
            problems.append({"flag": "locked_field_changed",
                             "detail": f"{k} differs between control "
                                       "and branch"})
        else:
            problems.append({"flag": "undeclared_field",
                             "detail": f"plan field {k} differs"})
    # transitive dependencies: copy changes must carry speech/captions/
    # picture inside the same region — stale mouth motion is not reusable
    for field, deps in DEPENDENT_OF.items():
        if field in allowed_fields:
            for dep in deps:
                if dep not in allowed_fields and dep not in \
                        variant.get("dependent_fields", []):
                    problems.append({
                        "flag": "dependency_outside_region",
                        "detail": f"{field} change requires {dep} inside "
                                  "the declared region"})
    return problems
