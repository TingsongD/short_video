"""Breakout math. Baseline = MEDIAN views of a channel's in-window videos,
excluding the candidate itself (so an outlier doesn't inflate its own baseline).
Stored in the contract's `channel_avg` field."""
from statistics import median


def channel_median(view_counts):
    counts = [v for v in view_counts if v is not None]
    return float(median(counts)) if counts else 0.0


def multiplier(views, baseline):
    return round(views / baseline, 2) if baseline > 0 else 0.0


def subs_ratio(views, subscribers):
    return round(views / subscribers, 2) if subscribers > 0 else 0.0


def is_breakout(*, views, baseline, subscribers, age_days, thresholds):
    if views <= 0 or age_days > thresholds["max_video_age_days"]:
        return False
    return (
        multiplier(views, baseline) >= thresholds["breakout_multiplier"]
        and subs_ratio(views, subscribers) >= thresholds["breakout_subs_ratio"]
    )
