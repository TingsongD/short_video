"""M10 verdict: win/loss vs channel baseline.
win = views >= win_views_multiplier * median AND
      avg_view_duration >= win_avd_ratio * video_length.
No windows yet -> 'pending'."""


def verdict(window, video_len_s, baseline_median_views, cfg):
    """window: one readback windows{} entry. Returns 'win'|'loss'|'pending'."""
    if not window:
        return "pending"
    import math
    if type(baseline_median_views) not in (int,float) or not math.isfinite(baseline_median_views) or baseline_median_views<=0:
        return 'pending'
    availability=window.get('availability',{})
    if any(availability.get(k,'ok') not in ('ok','verified_manual') for k in ('views','avg_view_duration_s')) or window.get('window_kind') in ('lifetime','source_calendar','unavailable'):
        return 'pending'
    views = window.get("views", 0)
    avd = window.get("avg_view_duration_s")
    views_win = views >= cfg["win_views_multiplier"] * baseline_median_views
    avd_win = (
        avd is not None and video_len_s
        and avd >= cfg["win_avd_ratio"] * video_len_s
    )
    return "win" if (views_win and avd_win) else "loss"


def format_promotion_signal(v):
    return {"win": "promote", "loss": "retire", "pending": "none"}[v]
