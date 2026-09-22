"""Read-only view of a slow provider operation.

Capacity and money are unchanged. Elapsed time is computed from the saved
acceptance time; a missing observation stays missing.
"""
from datetime import datetime, timezone

LIVE = ('accepted', 'running', 'succeeded', 'downloaded')


def _parse(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def provider_wait_view(wait, job, attempts, observations, *, now):
    if not isinstance(wait, dict) or not isinstance(wait.get('job_id'), str) or not wait['job_id']:
        return None
    chosen = None
    for attempt in attempts:
        if attempt['remote_id'] and attempt['status'] in LIVE:
            chosen = attempt
    if chosen is None:
        for attempt in attempts:
            if attempt['remote_id']:
                chosen = attempt
    last = None
    if chosen is not None:
        matches = [item['created_at'] for item in observations if item['attempt_id'] == chosen['id']]
        last = matches[-1] if matches else None
    started = chosen['created_at'] if chosen is not None else None
    start = _parse(started)
    moment = now if getattr(now, 'tzinfo', None) else None
    elapsed = None
    if start is not None and moment is not None:
        elapsed = max(0, int((moment - start).total_seconds()))
    next_poll = wait.get('next_attempt_at')
    reason = wait.get('reason')
    if job is not None:
        if job['next_attempt_at']:
            next_poll = job['next_attempt_at']
        if not reason and job['blocked_reason']:
            reason = job['blocked_reason']
    return {
        'job_id': wait['job_id'],
        'reason': reason,
        'operation_id': chosen['remote_id'] if chosen is not None else None,
        'started_at': started,
        'elapsed_s': elapsed,
        'last_observed_at': last,
        'next_poll_at': next_poll,
    }
