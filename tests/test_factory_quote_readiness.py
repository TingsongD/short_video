"""Premature quotes must not poison a later, fully bound local quote."""
from types import SimpleNamespace as NS

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.services.app import FactoryServices


def test_editorial_quote_waits_for_intent_and_has_bound_identity(monkeypatch):
    s = FactoryServices.__new__(FactoryServices)
    exp = NS(revision=9, packaging={'flashcut_policy': {'version': 1}})
    s._current = lambda *args: exp
    s._experiment_blueprint = lambda _: {'seed_id': 'seed'}
    s._analysis_binding_gate = lambda *args: None
    s.experiments = NS(_variant=lambda *args: NS(stale_reason=''))
    queued = []
    def enqueue(kind, body, **kw):
        queued.append((kind, body, kw))
        return {'job_id': kw['identity']}
    s.require = lambda _: NS(enqueue=enqueue)
    def missing(*args):
        raise ContractError('editorial_intent_required', 'quote')
    monkeypatch.setattr('modules.factory.services.editorial_work.output_binding', missing)
    with pytest.raises(ContractError, match='editorial_intent_required'):
        s.quote_experiment('exp', 9)
    assert queued == []
    binding = {'editorial_manifest': {'sha256': 'a'*64}, 'author_package_hash': 'b'*64}
    monkeypatch.setattr('modules.factory.services.editorial_work.output_binding', lambda *args: dict(binding))
    first = s.quote_experiment('exp', 9)
    assert s.quote_experiment('exp', 9) == first
    assert first['job_id'] != 'quote-exp-r9'
    assert queued[-1][1]['output_binding'] == binding
    binding['author_package_hash'] = 'c'*64
    assert s.quote_experiment('exp', 9) != first


def test_autorun_uses_same_quote_gate_as_api():
    from modules.factory.autorun.service import AutoRunService
    svc = AutoRunService.__new__(AutoRunService)
    calls = []
    def quote(eid, rev):
        calls.append((eid, rev))
        return {'job_id': 'quote-bound'}
    svc.s = NS(quote_experiment=quote)
    svc._put = lambda _: None
    run = NS(params={}, state={'experiment_id': 'exp', 'experiment_revision': 9})
    assert svc._stage_quote(run) == 'wait'
    assert calls == [('exp', 9)]
    assert run.state['quote_job'] == 'quote-bound'


def test_native_run_command_identity_changes_with_approved_plan(tmp_path):
    import json
    from modules.factory.store import Database
    s=FactoryServices.__new__(FactoryServices)
    s.db=Database(tmp_path/'run.db')
    exp=NS(revision=9,status='accepted',packaging={'flashcut_policy':{'version':1}})
    s._current=lambda *args:exp
    s._experiment_blueprint=lambda _: {'seed_id':'seed'}
    s._analysis_binding_gate=lambda *args:None
    plan={'id':'plan-first','plan_hash':'first'}
    s.plan_for=lambda _:plan
    s.require=lambda _:NS(enqueue=lambda kind,body,**kw:{'job_id':kw['identity']})
    with s.db.uow() as u:
        for name in ('first','fixed'):
            u.conn.execute('INSERT INTO meta(key,value) VALUES(?,?)',
                           ('local-run:plan-'+name,json.dumps({'plan_hash':name})))
    first=s.run_experiment('exp',9)
    assert s.run_experiment('exp',9)==first
    plan.update(id='plan-fixed',plan_hash='fixed')
    assert s.run_experiment('exp',9)!=first


def test_accepted_draft_still_authorizes_its_new_quote(tmp_path):
    from modules.factory.store import Database
    from modules.factory.autorun.service import AutoRunService
    svc=AutoRunService.__new__(AutoRunService)
    svc.s=NS(db=Database(tmp_path/'auth.db'),_current=lambda _:NS(status='accepted'),
        plan_for=lambda _: {'id':'new-plan','plan_hash':'new','total_price':{}},
        production=NS(_nodes=lambda _:{}))
    calls=[]
    class ReachedPlanApproval(Exception):pass
    def cover(*args,**kw):
        calls.append('current quote')
        raise ReachedPlanApproval
    svc._cover=cover
    svc._advance=lambda *args:calls.append('skipped')
    run=NS(state={'experiment_id':'exp','experiment_revision':9})
    with pytest.raises(ReachedPlanApproval):svc._stage_authorize(run)
    assert calls==['current quote']


def test_run_with_requoted_plan_returns_to_its_authorization():
    from modules.factory.autorun.service import AutoRunService
    svc=AutoRunService.__new__(AutoRunService)
    def run(*args):raise ContractError('not_authorized','plan')
    svc.s=NS(run_experiment=run)
    stages=[]
    svc._advance=lambda _,stage:stages.append(stage)
    assert svc._stage_run(NS(state={'experiment_id':'exp','experiment_revision':9}))=='next'
    assert stages==['authorize']
