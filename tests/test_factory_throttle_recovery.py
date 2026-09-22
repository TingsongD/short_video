"""Explicit analysis throttling is retryable; ambiguous submissions are not."""
import json
import pytest

from test_factory_auth_recovery import operation, states
from test_factory_api import env, mut
from modules.factory.testing.fakes import ProviderError
from modules.factory.execution.context import dispatch_context
from modules.factory.execution import Executor
from modules.factory.budget import BudgetService, ReservationBlocked
from modules.factory.domain.errors import ContractError
from test_factory_autorun import application, stack, make_seed, EXPIRY
from datetime import timedelta


def qc_job(application, failure):
    s, client, act, worker, root = stack(application)
    seed = s.seeds.get(make_seed(act, root))
    artifact = s.db.uow().artifacts.get(seed.source_asset_id)
    adapter = s.providers['audiovisual_analysis']
    calls = []
    def transport(*args):
        calls.append('POST')
        if failure == 'timeout':
            raise TimeoutError('lost')
        if failure == 'always' or len(calls) == 1:
            return 429, {}, b'{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}'
        result = {'verdict': 'pass', 'overlay': 'none', 'notes': []}
        return 200, {}, json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(result)}]}}]}).encode()
    adapter.transport = transport
    plan = s.effect_work.prepare('analysis', 'audiovisual_analysis', adapter.model,
        [{'task': 'review_clip', 'model': adapter.model, 'artifact_id': artifact['id'], 'artifact_sha256': artifact['sha256']}])
    auth = s.effect_work.authorize(plan['id'], {'plan_hash': plan['plan_hash'], 'reviewer': 'operator',
        'ceilings': plan['total'], 'budget_ids': ['credits-usd'], 'valid_until': EXPIRY})
    job = s.effect_work.queue(plan['id'], auth['authorization_id'])['jobs'][0]['job_id']
    return s, worker, job, calls


def test_qc_429_waits_then_retries_after_restart_without_rebuying_clip(application):
    from modules.factory.services.effect_work import EffectWork
    s, worker, job, calls = qc_job(application, 'once')
    out = worker.tick()
    assert out['status'] == 'pending', out
    assert out['reason'] == 'analysis_throttled'
    assert worker.tick() is None
    s.effect_work = EffectWork(s)  # no in-memory counters/backoff are needed
    future = s.scheduler.clock() + timedelta(seconds=31)
    s.scheduler.clock = lambda: future
    out = worker.tick()
    assert out['status'] == 'succeeded', out
    assert calls == ['POST', 'POST']
    assert [r[0] for r in s.db.conn.execute('SELECT status FROM attempts WHERE job_id=? ORDER BY attempt_seq', (job,))] == ['failed', 'succeeded']
    assert BudgetService(s.db).available('credits-usd') == 498


def test_qc_retry_exhaustion_survives_restart(application):
    from modules.factory.services.effect_work import EffectWork
    s, worker, job, calls = qc_job(application, 'always')
    for _ in range(3):
        out = worker.tick()
        s.effect_work = EffectWork(s)
        future = s.scheduler.clock() + timedelta(seconds=100)
        s.scheduler.clock = lambda: future
    assert out.get('error') == 'analysis_throttle_exhausted', out
    assert calls == ['POST'] * 3
    assert worker.tick() is None
    assert BudgetService(s.db).available('credits-usd') == 500


def test_worker_recovers_crash_between_throttle_receipt_and_executor_update(application):
    s, worker, job, calls = qc_job(application, 'once')
    assert worker.tick()['status'] == 'pending'
    attempt = s.effect_work._latest_attempt(job)
    # Adapter receipt exists, but simulate loss of the executor transaction.
    with s.db.uow() as u:
        u.conn.execute("UPDATE attempts SET status='dispatching' WHERE id=?", (attempt['id'],))
        u.conn.execute("UPDATE reservations SET status='held' WHERE id=?", (attempt['reservation_id'],))
        u.conn.execute("DELETE FROM events WHERE stream=? AND type='submit_failed'", ('attempt:' + attempt['id'],))
        u.conn.execute('UPDATE jobs SET next_attempt_at=NULL WHERE id=?', (job,))
    out = worker.tick()
    assert out['status'] == 'pending', out
    assert calls == ['POST']
    future = s.scheduler.clock() + timedelta(seconds=31)
    s.scheduler.clock = lambda: future
    assert worker.tick()['status'] == 'succeeded'
    assert calls == ['POST', 'POST']


def test_worker_recovers_failed_429_with_hold_not_yet_released(application):
    s, worker, job, calls = qc_job(application, 'once')
    assert worker.tick()['status'] == 'pending'
    attempt = s.effect_work._latest_attempt(job)
    with s.db.uow() as u:
        u.conn.execute("UPDATE reservations SET status='held' WHERE id=?", (attempt['reservation_id'],))
        u.conn.execute('UPDATE jobs SET next_attempt_at=NULL WHERE id=?', (job,))
    assert worker.tick()['status'] == 'pending'
    assert calls == ['POST']
    assert BudgetService(s.db).available('credits-usd') == 500
    future = s.scheduler.clock() + timedelta(seconds=31)
    s.scheduler.clock = lambda: future
    assert worker.tick()['status'] == 'succeeded'
    assert calls == ['POST', 'POST']


def test_qc_retry_rechecks_budget_and_unknown_is_not_retried(application):
    s, worker, job, calls = qc_job(application, 'once')
    assert worker.tick()['status'] == 'pending'
    BudgetService(s.db).tighten_budget('credits-usd', 0, 500, 'operator', 'Stop spend')
    future = s.scheduler.clock() + timedelta(seconds=31)
    s.scheduler.clock = lambda: future
    assert worker.tick()['error'] == 'reservation_blocked'
    assert calls == ['POST']


def test_qc_timeout_is_not_retried(application):
    s, worker, job, calls = qc_job(application, 'timeout')
    assert worker.tick()['error'] == 'analysis_timeout'
    future = s.scheduler.clock() + timedelta(seconds=1000)
    s.scheduler.clock = lambda: future
    assert worker.tick() is None
    assert calls == ['POST']
    assert s.db.conn.execute('SELECT status FROM attempts WHERE job_id=?', (job,)).fetchone()[0] == 'unknown'


def test_legacy_throttle_recovery_is_evidence_bound_and_bounded(application):
    s, worker, job, calls = qc_job(application, 'once')
    assert worker.tick()['status'] == 'pending'
    # Simulate the old worker's terminal treatment of the very same 429.
    s.db.conn.execute("UPDATE jobs SET status='failed',blocked_reason='analysis_http_error' WHERE id=?", (job,))
    assert s.effect_work.resume_throttled_job(job)
    assert not s.effect_work.resume_throttled_job(job)  # idempotent; no new paid attempt
    assert calls == ['POST']
    future = s.scheduler.clock() + timedelta(seconds=31)
    s.scheduler.clock = lambda: future
    assert worker.tick()['status'] == 'succeeded'
    assert not s.effect_work.resume_throttled_job(job)


def test_unknown_legacy_job_cannot_use_throttle_recovery(application):
    s, worker, job, calls = qc_job(application, 'timeout')
    worker.tick()
    s.db.conn.execute("UPDATE jobs SET blocked_reason='analysis_http_error' WHERE id=?", (job,))
    assert not s.effect_work.resume_throttled_job(job)
    assert calls == ['POST']


def test_retry_rechecks_expired_authority(application):
    s, worker, job, calls = qc_job(application, 'once')
    assert worker.tick()['status'] == 'pending'
    authority = json.loads(s.db.uow().records.get('appcommand', job)['body'])['input']['authorization_id']
    # Revocation simulates an authority withdrawn during the backoff window.
    s.db.conn.execute("UPDATE records SET status='revoked' WHERE kind='authorization' AND id=?", (authority,))
    future = s.scheduler.clock() + timedelta(seconds=31)
    s.scheduler.clock = lambda: future
    assert worker.tick()['error'] == 'authority_required'
    assert calls == ['POST']


def reject(operation, status=429):
    db, adapter, executor, attempt, request, credentials, calls = operation
    credentials.clear()
    def transport(*args):
        calls.append('POST')
        return status, {}, json.dumps({'error': {'code': status, 'message': 'Resource exhausted.'}}).encode()
    adapter.transport = transport
    return adapter, executor, attempt, request, calls


def test_explicit_429_has_durable_rejection_and_never_replays_same_attempt(operation):
    adapter, executor, attempt, request, calls = reject(operation)
    with pytest.raises(ProviderError, match='analysis_http_error'):
        executor.submit(attempt)
    assert states(operation[0], attempt) == ('failed', None, 'released')
    with dispatch_context({'attempt_id': attempt}):
        receipt = adapter.reconcile(request_hash='unused')
        assert receipt['status'] == 'failed'
        assert receipt['rejected']['http_status'] == 429
        assert adapter.submit(request)['status'] == 'failed'
    assert executor.reconcile(attempt)['status'] == 'failed'
    assert states(operation[0], attempt) == ('failed', None, 'released')
    assert calls == ['POST']


def test_crash_after_429_receipt_recovers_without_submission(operation):
    adapter, executor, attempt, request, calls = reject(operation)
    db = operation[0]
    db.conn.execute("UPDATE attempts SET status='dispatching' WHERE id=?", (attempt,))
    with dispatch_context({'attempt_id': attempt}), pytest.raises(ProviderError):
        adapter.submit(request)
    assert Executor(db, adapter).reconcile(attempt)['status'] == 'failed'
    assert states(db, attempt) == ('failed', None, 'released')
    assert calls == ['POST']


@pytest.mark.parametrize('field', ['attempt_id', 'request_hash', 'http_status'])
def test_mismatched_throttle_receipt_does_not_release_hold(operation, field):
    adapter, executor, attempt, request, calls = reject(operation)
    db = operation[0]
    db.conn.execute("UPDATE attempts SET status='dispatching' WHERE id=?", (attempt,))
    with dispatch_context({'attempt_id': attempt}), pytest.raises(ProviderError):
        adapter.submit(request)
    with dispatch_context({'attempt_id': attempt}):
        receipt = adapter.reconcile(request_hash='unused')
    receipt['rejected'][field] = 'mismatch'
    with pytest.raises(ContractError, match='rejection_evidence_mismatch'):
        executor._resolve_throttle(attempt, receipt)
    assert states(db, attempt)[2] == 'held'


def test_500_stays_unknown(operation):
    adapter, executor, attempt, request, calls = reject(operation, 500)
    with pytest.raises(ProviderError):
        executor.submit(attempt)
    assert executor.reconcile(attempt)['status'] == 'unknown'
    assert states(operation[0], attempt)[::2] == ('unknown', 'ambiguous')
    assert calls == ['POST']


def test_tighten_budget_preserves_holds_and_enforces_cumulative_limit(env):
    client, csrf, db, _, _ = env
    b = BudgetService(db)
    b.create_budget('run-usd', 'usd_micros', 'experiment', 'one-run', 100_000_000)
    held = b.reserve('old', [('run-usd', 17_000_000)])
    b.mark_ambiguous(held)
    before = [tuple(r) for r in db.conn.execute('SELECT * FROM reservation_lines')]
    body = {'ceiling': 50_000_000, 'expected_ceiling': 100_000_000,
            'reviewer': 'operator', 'evidence': 'Set this run to $50 total.'}
    response = mut(client, csrf, 'post', '/api/budgets/run-usd/tighten', json=body)
    assert response.status_code == 200, response.text
    assert b.available('run-usd') == 33_000_000
    assert [tuple(r) for r in db.conn.execute('SELECT * FROM reservation_lines')] == before
    assert mut(client, csrf, 'post', '/api/budgets/run-usd/tighten', json=body).json() == response.json()
    b.reserve('next', [('run-usd', 33_000_000)])
    with pytest.raises(ReservationBlocked):
        b.reserve('over', [('run-usd', 1)])
    assert db.conn.execute("SELECT count(*) FROM events WHERE type='budget_ceiling_tightened'").fetchone()[0] == 1


@pytest.mark.parametrize('cap,expected,error', [
    (101, 100, 'budget_not_tightened'), (50, 99, 'stale_budget_ceiling'),
    (9, 100, 'budget_below_committed'), (True, 100, 'invalid_cap'),
])
def test_unsafe_budget_tightening_rejected(env, cap, expected, error):
    _, _, db, _, _ = env
    b = BudgetService(db)
    b.create_budget('run', 'usd_micros', 'experiment', 'one-run', 100)
    b.reserve('old', [('run', 10)])
    with pytest.raises(ContractError, match=error):
        b.tighten_budget('run', cap, expected, 'operator', 'explicit change')
    assert b.available('run') == 90
