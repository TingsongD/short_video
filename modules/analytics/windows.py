"""M10 windows: 48h/7d/28d pull scheduling, timezone-safe.
Window names map to config readback.windows_hours [48, 168, 672]."""
from datetime import datetime, timedelta, timezone

WINDOW_NAMES = ["48h", "7d", "28d"]


def _parse(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def window_hours(cfg_hours):
    """[48, 168, 672] -> {'48h': 48, '7d': 168, '28d': 672}"""
    names = {48: '48h', 168: '7d', 672: '28d'}
    if any(type(h) is not int or h not in names for h in cfg_hours) or len(set(cfg_hours)) != len(cfg_hours):
        raise ValueError('readback windows must be unique supported hours: 48, 168, 672')
    return {names[h]: h for h in cfg_hours}


def pull_at(published_at, hours):
    return _parse(published_at) + timedelta(hours=hours)


def due_windows(publish_record, existing_windows, cfg_hours, now=None):
    """Window names whose pull time has passed and aren't recorded yet."""
    now = now or datetime.now(timezone.utc)
    done = set(existing_windows)
    return [
        name
        for name, hours in window_hours(cfg_hours).items()
        if name not in done and pull_at(publish_record["published_at"], hours) <= now
    ]


def next_due(publish_record, existing_windows, cfg_hours, now=None):
    """Next pending pull datetime, or None when all windows are done/due."""
    now = now or datetime.now(timezone.utc)
    future = [
        pull_at(publish_record["published_at"], h)
        for name, h in window_hours(cfg_hours).items()
        if name not in existing_windows
        and pull_at(publish_record["published_at"], h) > now
    ]
    return min(future) if future else None
