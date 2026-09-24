"""QA authorization errors must stop, not reopen themselves indefinitely."""
from types import SimpleNamespace

import pytest

from test_factory_api import env, mut
from modules.factory.autorun.service import AutoRun
from modules.factory.domain.records import Job


@pytest.mark.parametrize('reason', ['authority_required', 'reservation_identity_conflict'])
def test_footage_failure_never_reopens_paid_job_automatically(env, monkeypatch, reason):
    _, _, db, s, _ = env
    jid = 'qa-plan:pic:one'
    with db.uow() as u:
        u.jobs.put(Job(id=jid, schema_version='job.v1', created_at='now',
                       logical_key=jid, status='failed', blocked_reason=reason))
        u.conn.execute('UPDATE jobs SET blocked_reason=? WHERE id=?', (reason, jid))
    monkeypatch.setattr(s, 'plan_for', lambda _: {'id':'qa-plan'})
    monkeypatch.setattr(s.production, '_nodes', lambda _: {'pic:one':{'kind':'picture'}})
    run = AutoRun(id='qa-loop', stage='footage', state={'experiment_id':'qa-exp'})
    for _ in range(3):
        out = s.autorun._stage_footage(run)
        assert out[0:2] == ('pause', 'footage_failed')
        assert db.uow().jobs.get(jid)['status'] == 'failed'
        assert 'provider account' in out[3]
    assert not run.state.get('reopened_pictures')


def test_mismatched_account_is_rejected_before_authorization(env, monkeypatch):
    from modules.factory.domain.errors import ContractError
    _, _, _, s, _ = env
    monkeypatch.setattr(s.production, '_nodes', lambda _: {
        'pic:one': {'kind':'picture', 'status':'planned',
                    'provider':'google_vertex', 'allocations':[]}})
    s.providers['google_vertex'] = SimpleNamespace(account='configured-google-account')
    s.production.router = SimpleNamespace(adapters=s.providers)
    with pytest.raises(ContractError, match='provider_account_mismatch'):
        s.production.authorize('qa-plan', SimpleNamespace(), 'unrelated-canvas-account', [], '')


def test_resume_account_must_match_configured_route(env):
    client, csrf, _, s, _ = env
    s.providers['google_vertex'] = SimpleNamespace(account='google-account', models=['model'])
    s.autorun._put(AutoRun(id='account-resume', status='paused', stage='authorize',
                           params={'account':'wrong', 'budget_ids':[]}))
    bad = mut(client, csrf, 'post', '/api/autoruns/account-resume/resume', key='bad-account',
              json={'set_params':{'account':'another-wrong-account'}})
    assert bad.status_code == 400 and bad.json()['error'] == 'provider_account_mismatch'
    assert s.autorun.get('account-resume').params['account'] == 'wrong'
    good = mut(client, csrf, 'post', '/api/autoruns/account-resume/resume', key='good-account',
               json={'set_params':{'account':'google-account'}})
    assert good.status_code == 200
    assert s.autorun.get('account-resume').params['account'] == 'google-account'


def test_revised_plan_does_not_keep_old_dispatch_job(env, monkeypatch):
    _, _, _, s, _ = env
    monkeypatch.setattr(s, '_current', lambda _: SimpleNamespace(revision=2))
    run = AutoRun(id='new-plan', stage='footage', state={'experiment_id':'exp',
        'experiment_revision':1, 'plan_id':'old-plan', 'run_job':'old-dispatch'})
    s.autorun._rebind_current_revision(run)
    assert run.stage == 'quote'
    assert 'run_job' not in run.state and 'plan_id' not in run.state


@pytest.mark.parametrize('tag', ['reference_clip_one', 'reference_overlay_one', 'reference_check_one'])
def test_resume_cannot_replace_unresolved_reference_work(env, monkeypatch, tag):
    client, csrf, db, s, _ = env
    monkeypatch.setattr(s, '_current', lambda _: SimpleNamespace(revision=2))
    with db.uow() as u:
        u.jobs.put(Job(id='original-reference', schema_version='job.v1', created_at='now',
                       logical_key='original-reference', status='unknown'))
    s.autorun._put(AutoRun(id='reference-resume', status='paused', stage='quote',
        params={'workflow':{'version':2}}, state={'experiment_id':'exp','experiment_revision':1,
        tag+'_jobs':['original-reference']}))
    result = mut(client, csrf, 'post', '/api/autoruns/reference-resume/resume', key='reference-resume', json={})
    assert result.status_code == 400 and result.json()['error'] == 'prior_revision_inflight'
    assert s.autorun.get('reference-resume').status == 'paused'
    assert s.autorun.get('reference-resume').state['experiment_revision'] == 1


@pytest.mark.parametrize('status', ['ready', 'waiting_dependencies', 'awaiting_review'])
def test_revised_plan_retires_obsolete_local_work(env, monkeypatch, status):
    _, _, db, s, _ = env
    monkeypatch.setattr(s, '_current', lambda _: SimpleNamespace(revision=2))
    jid = 'old-plan:local'
    with db.uow() as u:
        u.jobs.put(Job(id=jid, schema_version='job.v1', created_at='now',
                       logical_key=jid, status=status, experiment_id='exp', revision=1))
    run = AutoRun(id='revised', stage='footage', params={'workflow':{'version':2}},
                  state={'experiment_id':'exp', 'experiment_revision':1, 'plan_id':'old-plan'})
    s.autorun._rebind_current_revision(run)
    assert run.stage == 'quote' and run.state['experiment_revision'] == 2
    assert db.uow().jobs.get(jid)['status'] == 'cancelled'
    assert db.uow().jobs.get(jid)['blocked_reason'] == 'superseded_by_revision:2'


@pytest.mark.parametrize('status', ['reserved', 'unknown', 'running'])
def test_revised_plan_preserves_potentially_active_jobs(env, monkeypatch, status):
    from modules.factory.domain.errors import ContractError
    _, _, db, s, _ = env
    monkeypatch.setattr(s, '_current', lambda _: SimpleNamespace(revision=2))
    jid = 'old-plan:active'
    with db.uow() as u:
        u.jobs.put(Job(id=jid, schema_version='job.v1', created_at='now',
                       logical_key=jid, status=status, experiment_id='exp', revision=1))
    run = AutoRun(id='revised', stage='footage', params={'workflow':{'version':2}},
                  state={'experiment_id':'exp', 'experiment_revision':1, 'plan_id':'old-plan'})
    with pytest.raises(ContractError, match='prior_revision_inflight'):
        s.autorun._rebind_current_revision(run)
    assert db.uow().jobs.get(jid)['status'] == status
    assert run.state['experiment_revision'] == 1


@pytest.mark.parametrize('attempt_status', ['prepared', 'dispatching', 'unknown', 'accepted', 'running', 'cancel_requested', 'succeeded'])
def test_retirement_never_changes_paid_attempts(env, attempt_status):
    from modules.factory.autorun.revisions import retire_local_jobs
    _, _, db, _, _ = env
    jid = 'old:queued'
    with db.uow() as u:
        u.jobs.put(Job(id=jid, schema_version='job.v1', created_at='now',
                       logical_key=jid, status='ready', experiment_id='exp', revision=1))
        u.conn.execute("INSERT INTO attempts(id,job_id,attempt_seq,status,body,created_at,updated_at) VALUES(?,?,1,?,'{}','now','now')", ('attempt',jid,attempt_status))
    before = [tuple(r) for r in db.conn.execute('SELECT * FROM attempts')]
    retired = retire_local_jobs(db, [jid], 'exp', 1, 2)
    assert bool(retired) == (attempt_status == 'succeeded')
    assert [tuple(r) for r in db.conn.execute('SELECT * FROM attempts')] == before
    assert retire_local_jobs(db, [jid], 'other-exp', 1, 2) == []
