"""Explicit legacy compatibility boundary (F32): the frozen legacy
readback contract cannot express missing metrics — its numeric fields
are non-nullable. These adapters map factory observations INTO that
contract; the None→0.0 collapse happens ONLY here, is documented on
every field, and never flows back into factory records.
"""


def legacy_window(snapshot):
    """MetricSnapshot -> legacy readback window dict. Unavailable
    metrics become 0 per the frozen schema; callers that need honesty
    use the snapshot's `availability` instead."""
    m = snapshot.get("metrics", {})
    return {
        "pulled_at": snapshot.get("observed_at", ""),
        "views": int(m["views"] or 0),
        "avg_view_duration_s": float(m["avg_view_duration_s"] or 0),
        "ctr": float(m["thumbnail_ctr"] or 0) / 100,
        "impressions": int(m["thumbnail_impressions"] or 0),
        "retention_points": [],
        "subs_gained": int(m["subs_gained"] or 0),
        "availability": dict(snapshot.get("availability", {})),
    }


def legacy_baseline(observed):
    """ReadbackService.baseline() result -> legacy 0.0 contract."""
    v = observed.get("median")
    return float(v) if v is not None else 0.0
