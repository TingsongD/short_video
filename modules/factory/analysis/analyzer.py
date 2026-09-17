"""Structured analysis payload validation (F12 checklist 3, automated:
malformed analysis output). A provider response that doesn't match the
shape is a typed contract failure, not a partial blueprint."""
from ..domain.errors import ContractError

ROLES = {"hook", "product_reveal", "proof", "payoff", "cta",
         "transition", "body"}
CONFIDENCE = {"reviewed", "uncertain", "unresolved"}


def _num(v, field, i):
    if type(v) not in (int, float) or v < 0:
        raise ContractError("malformed_analysis", field,
                            f"entry {i}: {v!r} not a non-negative number")
    return float(v)


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
