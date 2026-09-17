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
    import math
    if type(views) not in (int,float) or type(followers) not in (int,float) or not math.isfinite(views) or not math.isfinite(followers) or views<0 or followers<=0:
        return None
    return views / followers


def baseline_multiple(views, cohort_median):
    return follower_multiple(views,cohort_median)


def passes(mode, fm, bm, follower_threshold=2.0, baseline_threshold=5.0):
    from ..domain.errors import ContractError
    import math
    if mode not in MODES:
        raise ContractError('invalid_selection_mode','mode')
    if any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in (follower_threshold,baseline_threshold)):
        raise ContractError('invalid_threshold','threshold')
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
                           cohort.get("median_views") if cohort.get('available',True) and 'small_sample' not in cohort.get('flags',[]) else None)
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
            "platform":candidate.get('platform'),'creator_id':candidate.get('creator_id'),
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
