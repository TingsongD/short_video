"""Speech fitting (F19 checklist 4): fit a measured segment to its
target frame interval using documented limits only — silence trims,
padding, modest rate adjustment. A segment that cannot fit
intelligibly blocks for copy revision; words are never truncated.
"""
from ..domain.errors import ContractError

# Documented limits (seconds at the output clock):
TRIM_MAX_S = 0.9        # per edge
PAD_MAX_S = 2.0         # trailing pad inside the interval
RATE_MIN, RATE_MAX = 0.90, 1.10


def fit_plan(duration_s, target_s, trim_s=0.0):
    """duration_s: measured speech (after removing leading/trailing
    silence of `trim_s` each edge). → {"rate","pad_s","trim_s",
    "spoken_s","fits"} or ContractError naming the needed revision."""
    if duration_s is None:
        raise ContractError("duration_unknown", "duration_s",
                            "measure the waveform first")
    if target_s <= 0:
        raise ContractError("invalid_target", "target_s")
    if trim_s > TRIM_MAX_S:
        raise ContractError("trim_exceeds_limit", "trim_s",
                            f"{trim_s}>{TRIM_MAX_S}s per edge")
    spoken = duration_s - 2 * trim_s
    if spoken <= 0:
        raise ContractError("speech_too_short", "duration_s",
                            "silence trim would consume the segment")
    # 1) fits with room → pad
    if spoken <= target_s:
        pad = target_s - spoken
        if pad > PAD_MAX_S:
            return {"fits": False, "reason": "pad_exceeds_limit",
                    "pad_s": pad, "limit": PAD_MAX_S,
                    "action": "lengthen copy or accept shorter speech"}
        return {"fits": True, "rate": 1.0, "pad_s": pad,
                "trim_s": trim_s, "spoken_s": spoken}
    # 2) modest rate adjustment
    rate = spoken / target_s
    if rate <= RATE_MAX:
        return {"fits": True, "rate": rate, "pad_s": 0.0,
                "trim_s": trim_s, "spoken_s": spoken}
    # 3) too long even at max rate — copy revision, never truncation
    return {"fits": False, "reason": "speech_too_long",
            "spoken_s": spoken, "target_s": target_s,
            "rate_needed": round(rate, 4),
            "rate_limit": RATE_MAX,
            "action": "revise copy or regenerate within authorization"}


def apply_fit(word_times, fit):
    """Map source word times through the fit: trim offset, rate, pad.
    → [{"w","start_s","end_s"}] in target-interval time."""
    if not fit.get("fits"):
        raise ContractError("unfitted_speech", "fit", fit.get("reason"))
    rate, trim = fit["rate"], fit.get("trim_s", 0.0)
    return [{"w": w["w"],
             "start_s": max(0.0, (w["start_s"] - trim) * rate),
             "end_s": max(0.0, (w["end_s"] - trim) * rate)}
            for w in word_times]
