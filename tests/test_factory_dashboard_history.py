"""Offline public-boundary coverage for reversible dashboard-only archiving."""
import pytest

from modules.factory.autorun.service import AutoRun
from modules.factory.domain.records import Job
from modules.factory.services.history import DashboardHistory
from test_factory_api import env, mut


def job(db, jid, status='succeeded', experiment='', depends=()):
    with db.uow() as u:
        u.jobs.put(Job(id=jid, logical_key=jid, phase='render', status=status,
                       experiment_id=experiment, depends_on=list(depends)))


def run(db, rid, status='succeeded', **kw):
    with db.uow() as u:
        u.records.put(AutoRun(id=rid, schema_version='autorun.v1', status=status, **kw))


def items(env):
    return env[0].get('/api/dashboard/history').json()['items']


def change(env, targets, action='archive', key='archive'):
    return mut(env[0], env[1], 'post', '/api/dashboard/history', key=key,
               json={'action': action, 'targets': targets})


def execution_snapshot(db):
    tables = ('jobs', 'attempts', 'budgets', 'reservations', 'reservation_lines',
              'artifacts', 'intents', 'outbox', 'capacity_holds', 'scheduler_flags')
    return {**{table: [dict(r) for r in db.conn.execute('SELECT * FROM ' + table)] for table in tables},
            'records': [dict(r) for r in db.conn.execute("SELECT * FROM records WHERE kind!='api_request'")]}


def test_archive_restore_persists_without_execution_or_accounting_changes(env):
    _, _, db, _, root = env
    job(db, 'old-job'); run(db, 'old-run', state={'production_jobs': ['old-job']})
    sentinel = root / 'keep-video.mp4'; sentinel.write_bytes(b'untouched')
    before = execution_snapshot(db)
    targets = items(env)
    result = change(env, targets)
    assert result.status_code == 200, result.json()
    assert result.json()['counts'] == {'job': 1, 'run': 1}
    assert change(env, targets).json() == result.json()  # idempotent replay
    assert all(i['archived'] for i in items(env))
    assert all(i['archived'] for i in DashboardHistory(db).snapshot()['items'])
    queue = env[0].get('/api/collections/queue').json()['items']
    assert queue['jobs'][0]['id'] == 'old-job'  # authoritative collection is not deleted/filtered
    assert all(i['archived'] for i in queue['history']['items'])
    assert execution_snapshot(db) == before
    assert change(env, items(env), 'restore', 'restore').status_code == 200
    assert not any(i['archived'] for i in items(env))
    assert execution_snapshot(db) == before
    assert sentinel.read_bytes() == b'untouched'


@pytest.mark.parametrize('status', ['ready', 'waiting_dependencies', 'reserved', 'dispatching',
                                 'accepted', 'running', 'unknown', 'blocked', 'cancel_requested',
                                 'awaiting_review', 'output_available', 'downloaded'])
def test_nonterminal_jobs_and_experiment_history_stay_visible(env, status):
    db = env[2]
    job(db, 'old-job', experiment='exp-one')
    job(db, 'current-job', status, experiment='exp-one')
    run(db, 'old-run', experiment_id='exp-one')
    assert all(not i['eligible'] and not i['archived'] for i in items(env))
    assert change(env, items(env)).status_code == 409


@pytest.mark.parametrize('status', ['paused', 'running'])
def test_run_protects_referenced_jobs_commands_and_dependencies(env, status):
    db, services = env[2:4]
    job(db, 'old-job'); job(db, 'dependency')
    job(db, 'finished-child', depends=['dependency'])
    run(db, 'current-run', status, state={'nested': {'jobs': ['old-job', 'finished-child']}})
    services.commands.enqueue('auto_step', {'run_id': 'current-run'}, identity='step')
    with db.uow() as u:
        u.conn.execute("UPDATE jobs SET status='succeeded' WHERE id='step'")
    assert all(not i['eligible'] for i in items(env))


@pytest.mark.parametrize('attempt_status', ['prepared', 'dispatching', 'unknown', 'accepted', 'running', 'cancel_requested'])
def test_failed_job_with_unresolved_provider_attempt_cannot_be_archived(env, attempt_status):
    db = env[2]; job(db, 'failed-job', 'failed')
    with db.uow() as u:
        u.conn.execute("INSERT INTO attempts(id,job_id,attempt_seq,status,body,created_at,updated_at) VALUES('attempt','failed-job',0,?,'{}','now','now')", (attempt_status,))
    assert not items(env)[0]['eligible']
    assert change(env, items(env)).status_code == 409


def test_retained_work_protects_terminal_job(env):
    db = env[2]; job(db, 'failed-job', 'failed')
    with db.uow() as u:
        u.conn.execute("INSERT INTO capacity_holds VALUES('render','failed-job','worker',1,'2000-01-01','unfinished_local_work')")
    assert not items(env)[0]['eligible']


def test_stale_preview_is_atomic_and_reopened_work_reappears(env):
    db = env[2]; job(db, 'old-job'); job(db, 'other-job')
    targets = items(env)
    with db.uow() as u:
        u.conn.execute("UPDATE jobs SET status='ready',version=version+1 WHERE id='other-job'")
    assert change(env, targets).status_code == 409
    assert not any(i['archived'] for i in items(env))
    assert change(env, [i for i in items(env) if i['eligible']], key='fresh').status_code == 200
    with db.uow() as u:
        u.conn.execute("UPDATE jobs SET status='running',version=version+1 WHERE id='old-job'")
    assert not any(i['archived'] for i in items(env))
    with db.uow() as u:
        u.conn.execute("UPDATE jobs SET status='succeeded',version=version+1 WHERE id='old-job'")
    assert not next(i for i in items(env) if i['id'] == 'old-job')['archived']


def test_new_unresolved_work_unhides_previously_archived_run_and_job(env):
    db = env[2]; job(db, 'old-job', experiment='exp-one')
    run(db, 'old-run', experiment_id='exp-one')
    assert change(env, items(env)).status_code == 200
    job(db, 'new-job', 'ready', experiment='exp-one')
    assert not any(i['archived'] for i in items(env))


def test_history_mutations_require_csrf_and_idempotency(env):
    client, csrf, db, *_ = env; job(db, 'old-job')
    body = {'action': 'archive', 'targets': items(env)}
    assert client.post('/api/dashboard/history', json=body).status_code == 403
    assert client.post('/api/dashboard/history', json=body, headers={'x-csrf-token': csrf}).status_code == 400
    assert change(env, [], key='empty').status_code == 400
    assert change(env, [{'kind': 'budget', 'id': 'anything', 'version_hash': 'x'}], key='invalid').status_code == 400
