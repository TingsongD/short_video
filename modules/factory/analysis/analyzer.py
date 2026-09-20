"""Structured analysis payload validation (F12 checklist 3, automated:
malformed analysis output). A provider response that doesn't match the
shape is a typed contract failure, not a partial blueprint."""
import math

from ..domain.errors import ContractError

ROLES = {"hook", "product_reveal", "proof", "payoff", "cta",
         "transition", "body"}
CONFIDENCE = {"reviewed", "uncertain", "unresolved"}

# Provider-declared seconds are descriptive, not frame-authoritative —
# seams up to this size are tolerated and absorbed when the timeline is
# built. Beyond it the timing is structurally invalid: a gap, an overlap,
# or coverage that stops early is never silently stretched to fit.
TIMING_TOL_S = 0.5
# A beat shorter than ~5 output frames cannot carry a shot.
MIN_BEAT_S = 0.15


def _num(v, field, i):
    if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
        raise ContractError("malformed_analysis", field,
                            f"entry {i}: {v!r} not a non-negative "
                            "finite number")
    return float(v)


def _check_segments(segs, field, duration_s, tol_s, allow_gaps):
    """Bounds + ordering validation for one interval list. Returns the
    last end, or None for an empty list."""
    prev_end = None
    for i, b in enumerate(segs):
        s, e = b["start_s"], b["end_s"]
        if not (math.isfinite(s) and math.isfinite(e)):
            raise ContractError(
                "invalid_analysis_timing", field,
                f"entry {i}: non-finite bounds {s!r}–{e!r}")
        if e <= s:
            raise ContractError(
                "invalid_analysis_timing", field,
                f"entry {i}: end {e} <= start {s}")
        if prev_end is not None:
            if s < prev_end - tol_s:
                raise ContractError(
                    "invalid_analysis_timing", field,
                    f"entry {i} starts {prev_end - s:.2f}s before the "
                    "previous entry ends — material overlap")
            if not allow_gaps and s - prev_end > tol_s:
                raise ContractError(
                    "invalid_analysis_timing", field,
                    f"entry {i}: {s - prev_end:.2f}s unaccounted gap "
                    "after the previous entry")
        if e > duration_s + tol_s:
            raise ContractError(
                "invalid_analysis_timing", field,
                f"entry {i} ends {e - duration_s:.2f}s beyond the "
                f"verified media duration {duration_s:.2f}s")
        prev_end = e
    return prev_end


def validate_temporal(analysis, duration_s, *, tol_s=TIMING_TOL_S,
                      min_beat_s=MIN_BEAT_S):
    """Reject beat timing that cannot describe the verified media:
    non-finite or out-of-order bounds, material overlaps or gaps,
    implausibly short beats, and coverage that stops far short of the
    probed duration. The only correction permitted downstream is snapping
    the final beat's tail — bounded by tol_s — to the verified duration.
    Raises invalid_analysis_timing (a ContractError); returns None."""
    if type(duration_s) not in (int, float) or \
            not math.isfinite(duration_s) or duration_s <= 0:
        raise ContractError(
            "invalid_analysis_timing", "duration_s",
            "verified media duration is required before beat timing "
            "can be trusted")
    beats = analysis.get("beats") or []
    if not beats:
        raise ContractError("invalid_analysis_timing", "beats", "empty")
    for i, b in enumerate(beats):
        if b["end_s"] - b["start_s"] < min_beat_s:
            raise ContractError(
                "invalid_analysis_timing", "beats",
                f"entry {i}: {b['end_s'] - b['start_s']:.3f}s beat is "
                "too short to carry a shot")
    prev_end = _check_segments(beats, "beats", duration_s, tol_s, False)
    if beats[0]["start_s"] > tol_s:
        raise ContractError(
            "invalid_analysis_timing", "beats",
            f"the first beat starts {beats[0]['start_s']:.2f}s in — "
            "the head of the media is unaccounted for")
    if duration_s - prev_end > tol_s:
        raise ContractError(
            "invalid_analysis_timing", "beats",
            f"beats cover {prev_end:.2f}s of a verified "
            f"{duration_s:.2f}s source — the remaining "
            f"{duration_s - prev_end:.2f}s is unaccounted for")
    # Transcript gaps are legal (silence); ordering and bounds are not.
    _check_segments(analysis.get("transcript") or [], "transcript",
                    duration_s, tol_s, True)


def assign_passages(beats, transcript):
    """Assign every transcript passage to exactly one beat — single
    ownership, never duplicated across adjacent beats. A passage belongs
    to the beat containing its start; when the start falls in a seam the
    beat containing the midpoint owns it, then the beat containing its
    end. A passage whose timing lands in no beat is 'unplaced' and must
    be reported, not silently dropped.
    → {"by_beat": {beat_id: [passage, ...]}, "unplaced": [...]}"""
    by_beat = {}
    unplaced = []
    for b in beats:
        by_beat.setdefault(b.get("id"), [])
    for t in transcript:
        start, end = t.get("start_s"), t.get("end_s")
        owner = None
        if start is not None:
            owner = next((b for b in beats
                          if b["start_s"] <= start < b["end_s"]), None)
        if owner is None and start is not None and end is not None:
            mid = (start + end) / 2.0
            owner = next((b for b in beats
                          if b["start_s"] <= mid < b["end_s"]), None)
        if owner is None and end is not None:
            owner = next((b for b in beats
                          if b["start_s"] < end <= b["end_s"]), None)
        if owner is None:
            unplaced.append(t)
        else:
            by_beat[owner.get("id")].append(t)
    return {"by_beat": by_beat, "unplaced": unplaced}


def _segment(seg, i, field):
    if not isinstance(seg, dict):
        raise ContractError("malformed_analysis", field,
                            f"entry {i} not an object")
    start = _num(seg.get("start_s"), field, i)
    end = _num(seg.get("end_s"), field, i)
    if end <= start:
        raise ContractError("malformed_analysis", field,
                            f"entry {i}: end {end} <= start {start}")
    out = {"id": str(seg.get("id") or f"{field}-{i}"),
           "start_s": start, "end_s": end}
    return out


def parse_analysis(payload):
    """→ {"beats", "transcript", "music", "uncertainty"} or raise."""
    if not isinstance(payload, dict):
        raise ContractError("malformed_analysis", "payload",
                            "not an object")
    beats = []
    for i, b in enumerate(payload.get("beats") or []):
        seg = _segment(b, i, "beats")
        role = b.get("role")
        if role not in ROLES:
            raise ContractError("malformed_analysis", "beats",
                                f"entry {i}: unknown role {role!r}")
        conf = b.get("confidence", "uncertain")
        if conf not in CONFIDENCE:
            raise ContractError("malformed_analysis", "beats",
                                f"entry {i}: bad confidence {conf!r}")
        beats.append({**seg, "role": role, "confidence": conf,
                      "visual_event": str(b.get("visual_event") or "")})
    if not beats:
        raise ContractError("malformed_analysis", "beats", "empty")
    transcript = []
    for i, t in enumerate(payload.get("transcript") or []):
        seg = _segment(t, i, "transcript")
        words = []
        for j, w in enumerate(t.get("words") or []):
            ws = _segment(w, j, "transcript.words")
            if ws["start_s"] < seg["start_s"] - 1e-6 or \
                    ws["end_s"] > seg["end_s"] + 1e-6:
                raise ContractError(
                    "malformed_analysis", "transcript.words",
                    f"word {j} outside segment {i} bounds")
            words.append({**ws, "text": str(w.get("text") or "")})
        transcript.append({**seg, "text": str(t.get("text") or ""),
                           "words": words})
    music = payload.get("music") or {}
    return {"beats": beats, "transcript": transcript,
            "music": {"role": str(music.get("role") or "unknown")},
            "uncertainty": [str(u)
                            for u in payload.get("uncertainty") or []]}
