"""Outlier evaluation (F10 checklist 3–4): follower and baseline ratios
are independent metrics; provider scores are kept distinct, never
relabeled as our computed ratio.

- follower: strict views > followers * threshold (default 2)
- baseline: views >= cohort_median * threshold (default 5, inclusive)
- modes: follower | baseline | either | both — the mode is persisted
  with the run, no hidden follower-only gate

Hidden/zero denominators produce null multiples — never infinity, never
zero-as-evidence.
"""

MODES = ("follower", "baseline", "either", "both")


def follower_multiple(views, followers):
    if views is None or followers in (None, 0):
        return None
    return views / followers


def baseline_multiple(views, cohort_median):
    if views is None or cohort_median in (None, 0):
        return None
    return views / cohort_median


def passes(mode, fm, bm, follower_threshold=2.0, baseline_threshold=5.0):
    if mode not in MODES:
        raise ValueError(f"unknown selection_mode {mode!r}")
    f = fm is not None and fm > follower_threshold      # strict
    b = bm is not None and bm >= baseline_threshold     # inclusive
    return {"follower": f, "baseline": b,
            "either": f or b, "both": f and b}[mode]


def evaluate(candidate, cohort, mode="either", follower_threshold=2.0,
             baseline_threshold=5.0):
    """candidate: {post_id, views, followers, provider_score?}.
    Returns explainable verdict with all denominators recorded."""
    fm = follower_multiple(candidate.get("views"),
                           candidate.get("followers"))
    bm = baseline_multiple(candidate.get("views"),
                           cohort.get("median_views"))
    reasons = []
    confidence = "standard"
    if candidate.get("views") is None:
        reasons.append("views_unavailable")
        confidence = "insufficient"
    if candidate.get("followers") in (None, 0):
        reasons.append("followers_unavailable")
    if cohort.get("median_views") is None:
        reasons.append("baseline_unavailable")
    if "small_sample" in cohort.get("flags", []):
        reasons.append("small_sample")
        if confidence == "standard":
            confidence = "low"
    if "mixed_periods" in cohort.get("flags", []):
        reasons.append("mixed_periods")
        if confidence == "standard":
            confidence = "low"
    selected = passes(mode, fm, bm, follower_threshold, baseline_threshold)
    if not selected:
        reasons.append(f"below_{mode}_threshold")
    return {"post_id": candidate.get("post_id"),
            "views": candidate.get("views"),
            "followers": candidate.get("followers"),
            "follower_multiple": fm,
            "baseline_multiple": bm,
            "provider_score": candidate.get("provider_score"),
            "cohort_size": cohort.get("size"),
            "cohort_median_views": cohort.get("median_views"),
            "selected": selected,
            "confidence": confidence,
            "reasons": reasons}
