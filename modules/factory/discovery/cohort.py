"""Comparable-video cohort construction (F10 checklist 2).

The cohort is the creator's *preceding* comparable posts — never the
seed itself, never future posts, never mixed formats. Every inclusion
and exclusion is recorded with its reason so an engineer can recompute
every ratio from stored evidence."""
from statistics import mean, median

from ..domain.errors import ContractError

DEFAULT_MIN = 20
DEFAULT_MAX = 50
MIXED_PERIOD_DAYS = 30


def _day(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def build_cohort(seed, videos, min_size=DEFAULT_MIN, max_size=DEFAULT_MAX,
                 now=None):
    """seed/video dicts: post_id, views, published_at, format, platform.
    Returns included/excluded lists + mean/median + confidence flags."""
    included, excluded = [], []
    for v in videos:
        pid = v.get("post_id")
        reason = None
        if pid == seed.get("post_id"):
            reason = "is_seed"
        elif v.get("platform") and seed.get("platform") \
                and v["platform"] != seed["platform"]:
            reason = "different_platform"
        elif v.get("format") != seed.get("format"):
            reason = "mixed_format"
        elif v.get("published_at") is None:
            reason = "missing_publication_date"
        elif seed.get("published_at") and _day(v["published_at"]) >= \
                _day(seed["published_at"]):
            reason = "published_after_seed"
        elif v.get("views") is None:
            reason = "missing_views"
        if reason:
            excluded.append({"post_id": pid, "reason": reason})
        else:
            included.append(v)
    # Most recent first; bound at max_size.
    included.sort(key=lambda v: v["published_at"], reverse=True)
    if len(included) > max_size:
        for v in included[max_size:]:
            excluded.append({"post_id": v["post_id"],
                             "reason": "beyond_cohort_max"})
        included = included[:max_size]
    counts = [v["views"] for v in included]
    flags = []
    if len(included) < min_size:
        flags.append("small_sample")
    if included:
        span = (_day(included[0]["published_at"])
                - _day(included[-1]["published_at"])).days
        if span > MIXED_PERIOD_DAYS:
            flags.append("mixed_periods")
    return {"included": [v["post_id"] for v in included],
            "excluded": excluded,
            "size": len(included),
            "mean_views": mean(counts) if counts else None,
            "median_views": median(counts) if counts else None,
            "flags": flags}
