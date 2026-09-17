"""Timing derivation (F08 checklist 2–3).

Per job: queue wait, provider-observed elapsed, collection delay, review
time, render time and wall clock — derived from durable event timestamps,
never invented. When the provider doesn't report a finish time, the
succeeded event carries an uncertainty flag instead of a fabricated
completion timestamp.
"""
from datetime import datetime


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _delta(a, b):
    return (_t(b) - _t(a)).total_seconds()


def timeline(events):
    """events: ordered dicts for one job/attempt stream.
    Returns {durations: {stage: seconds|None}, uncertainty: [...]}."""
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)

    def first(t):
        return by_type.get(t, [None])[0]

    def last(t):
        return by_type.get(t, [None])[-1]

    d = {}
    uncertainty = []

    def span(start_type, end_type, key):
        s, f = first(start_type), last(end_type)
        if s and f:
            d[key] = _delta(s["created_at"], f["created_at"])
        else:
            d[key] = None

    # Queue wait: first scheduling signal (planned or prepared) → claimed.
    qstart = first("planned") or first("prepared") or first("ready")
    claimed = first("claimed")
    d["queue_wait_s"] = (_delta(qstart["created_at"], claimed["created_at"])
                         if qstart and claimed else None)
    span("dispatch_started", "accepted", "dispatch_s")
    # Provider elapsed: only trustworthy when the provider reported a
    # finish time inside the event body; otherwise record uncertainty.
    acc = first("accepted")
    fin = first("provider_finished")
    if acc and fin:
        provider_finished_at = (fin.get("body") or {})
        if isinstance(provider_finished_at, str):
            import json
            provider_finished_at = json.loads(provider_finished_at)
        pf = provider_finished_at.get("provider_finished_at")
        if pf:
            d["provider_elapsed_s"] = _delta(acc["created_at"], pf)
            if fin["created_at"] != pf:
                uncertainty.append(
                    "provider_finished_at is provider-reported; "
                    "observation delay included in collection_delay")
        else:
            d["provider_elapsed_s"] = _delta(acc["created_at"],
                                             fin["created_at"])
            uncertainty.append(
                "provider did not report finish time; elapsed is "
                "observed-poll time, not true completion")
    else:
        d["provider_elapsed_s"] = None
    span("provider_finished", "downloaded", "collection_delay_s")
    span("review_started", "review_finished", "review_s")
    span("render_started", "render_finished", "render_s")
    span("planned", "downloaded", "wall_clock_s")
    span("accepted", "downloaded", "turnaround_s")
    return {"durations": d, "uncertainty": uncertainty}
