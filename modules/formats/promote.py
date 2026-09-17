"""M3 promotion: readback-driven lifecycle.
- >= promote_min_videos our-channel videos AND avg multiplier >=
  promote_min_multiplier (vs our channel median)  -> proven
- >= retire_consecutive_losses consecutive losing readbacks -> retired
  (checked first — recent failure outweighs stale success)

`consecutive_losses` lives inside our_stats (schema allows extra props).
"""


def _mult(readback):
    base = readback.get("baseline_median_views") or 0
    views = max(w.get("views", 0) for w in readback.get("windows", {}).values()) if readback.get("windows") else 0
    return views / base if base > 0 else 0.0


def apply_readback(entry, readback):
    """Fold one readback verdict into entry.our_stats. Returns the entry."""
    stats = entry.setdefault(
        "our_stats", {"videos": 0, "wins": 0, "avg_multiplier": 0}
    )
    stats.setdefault("consecutive_losses", 0)
    if readback.get('verdict') not in ('win','loss') or not readback.get('baseline_median_views',0):
        return entry
    windows=readback.get('windows',{})
    if not windows or any(w.get('window_kind') in ('lifetime','source_calendar','unavailable') or w.get('availability',{}).get('views','ok')!='ok' for w in windows.values()):
        return entry
    m = _mult(readback)
    n = stats["videos"]
    stats["avg_multiplier"] = round(
        (stats.get("avg_multiplier", 0) * n + m) / (n + 1), 3
    )
    stats["videos"] = n + 1
    if readback["verdict"] == "win":
        stats["wins"] += 1
        stats["consecutive_losses"] = 0
    elif readback["verdict"] == "loss":
        stats["consecutive_losses"] += 1
    return entry


def evaluate(entry, cfg):
    """Return the status the entry should have given our_stats + config."""
    stats = entry.get("our_stats", {})
    if stats.get("consecutive_losses", 0) >= cfg["retire_consecutive_losses"]:
        return "retired"
    if (
        stats.get("videos", 0) >= cfg["promote_min_videos"]
        and stats.get("avg_multiplier", 0) >= cfg["promote_min_multiplier"]
    ):
        return "proven"
    return entry["status"]


def update_entry(entry, readback, cfg):
    """apply_readback + evaluate -> set status. Returns (entry, changed)."""
    old = entry["status"]
    apply_readback(entry, readback)
    entry["status"] = evaluate(entry, cfg)
    return entry, entry["status"] != old
