"""Renderer package fixes re-quote locally while paid outcomes stay immutable."""
from types import SimpleNamespace as NS

import pytest

from modules.factory.autorun.service import AutoRunService
from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import Job
from modules.factory.store import Database


def scenario(tmp_path, monkeypatch, status='waiting_dependencies'):
    db=Database(tmp_path/'recovery.db')
    exp=NS(revision=9,packaging={'flashcut_policy':{'renderer':'hypit_primary.v1'}})
    old={'author_package_hash':'old','editorial_manifest':{'sha256':'same'},'policy_hash':'same'}
    new={**old,'author_package_hash':'fixed'}
    node={'kind':'compose','request':{'output_binding':old}}
    svc=NS(db=db,_current=lambda _:exp,production=NS(_nodes=lambda _: {'cmp:A':node}))
    auto=AutoRunService(svc)
    run=NS(stage='compose',params={'workflow':{'version':2}},pause={'code':'render_failed'},notes=[],
        state={'experiment_id':'exp','experiment_revision':9,'plan_id':'plan-old',
               'quote_job':'old-quote','production_jobs':['plan-old:cmp:A'], 'tts_done':True})
    with db.uow() as u:
        u.jobs.put(Job(schema_version='job.v1',id='plan-old:cmp:A',logical_key='plan-old:cmp:A',
            experiment_id='exp',revision=9,phase='render',status=status))
    monkeypatch.setattr('modules.factory.services.editorial_work.output_binding',lambda *_:new)
    return auto,run,db,old,new


def test_resume_after_package_fix_requotes_without_changing_draft_or_narration(tmp_path,monkeypatch):
    auto,run,db,old,new=scenario(tmp_path,monkeypatch)
    auto._rebind_current_revision(run)
    assert run.stage=='quote'
    assert run.state['experiment_revision']==9 and run.state['tts_done']
    assert 'plan_id' not in run.state and 'quote_job' not in run.state
    assert db.uow().jobs.get('plan-old:cmp:A')['status']=='cancelled'
    assert run.state['author_package_rebuilds'][-1]['prior_plan_id']=='plan-old'


def test_package_fix_cannot_replace_inflight_work(tmp_path,monkeypatch):
    auto,run,db,_,_=scenario(tmp_path,monkeypatch,'running')
    with pytest.raises(ContractError,match='prior_render_inflight'):
        auto._rebind_current_revision(run)
    assert run.state['plan_id']=='plan-old'


def test_package_recovery_does_not_adopt_changed_editorial(tmp_path,monkeypatch):
    auto,run,_,_,new=scenario(tmp_path,monkeypatch)
    new['editorial_manifest']={'sha256':'changed'}
    with pytest.raises(ContractError,match='stale_editorial_plan'):
        auto._rebind_current_revision(run)


def test_unchanged_package_keeps_existing_plan(tmp_path,monkeypatch):
    auto,run,_,old,new=scenario(tmp_path,monkeypatch)
    new.update(old)
    auto._rebind_current_revision(run)
    assert run.state['plan_id']=='plan-old' and run.stage=='compose'
