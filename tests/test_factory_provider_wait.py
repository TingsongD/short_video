"""Slow generation exposes the saved operation without touching its accounting."""
from datetime import datetime, timezone

from modules.factory.autorun.waiting import provider_wait_view


def test_waiting_view_reports_elapsed_observation_and_next_poll():
    now = datetime(2026, 9, 22, 12, 0, 10, tzinfo=timezone.utc)
    job = {'next_attempt_at': '2026-09-22T12:00:40Z', 'blocked_reason': 'remote_unfinished'}
    attempts = [{'id': 'a1', 'remote_id': 'operations/123', 'status': 'running',
                 'created_at': '2026-09-22T12:00:00Z'}]
    view = provider_wait_view(
        {'job_id': 'job-1', 'reason': 'remote_unfinished'}, job, attempts,
        [{'attempt_id': 'a1', 'created_at': '2026-09-22T12:00:08Z'}], now=now)
    assert view == {
        'job_id': 'job-1', 'reason': 'remote_unfinished',
        'operation_id': 'operations/123', 'started_at': '2026-09-22T12:00:00Z',
        'elapsed_s': 10, 'last_observed_at': '2026-09-22T12:00:08Z',
        'next_poll_at': '2026-09-22T12:00:40Z'}


def test_unconfirmed_submission_has_no_invented_observation():
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    view = provider_wait_view(
        {'job_id': 'job-1', 'reason': 'remote_unfinished', 'next_attempt_at': '2026-09-22T12:01:00Z'},
        None, [{'id': 'a1', 'remote_id': None, 'status': 'unknown', 'created_at': '2026-09-22T12:00:00Z'}],
        [], now=now)
    assert view['operation_id'] is None
    assert view['elapsed_s'] is None
    assert view['last_observed_at'] is None
    assert view['next_poll_at'] == '2026-09-22T12:01:00Z'
