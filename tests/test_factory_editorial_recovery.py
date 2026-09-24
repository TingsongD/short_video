import hashlib,json
from types import SimpleNamespace
import pytest
from test_factory_editorial_planning import case
from modules.factory.autorun.editorial_recovery import adopt_local_plan
from modules.factory.analysis.source_evidence import SourceEvidenceService
from modules.factory.store import Database
from modules.factory.domain.records import content_hash
from modules.factory.execution.effects import wire_hash
from modules.factory.domain.errors import ContractError


@pytest.mark.parametrize('bad',[None,'missing','finish','request','current','remote','previous_revision','changed_same_revision'])
def test_editorial_local_adoption_requires_completed_bound_answer_and_preserves_money(tmp_path,monkeypatch,bad):
    db=Database(tmp_path/'db');store=SourceEvidenceService(db,tmp_path/'source_evidence')
    inputs,_=case();binding={'experiment_id':'exp','revision':1,'understanding':'a'*64};evidence={'source_sha256':'b'*64}
    request={'task':'plan_flashcut_edits','model':'model','editorial_input':inputs,'editorial_binding':binding,'binding':evidence}
    aid='attempt';jid='job';root=tmp_path/'provider';folder=root/('sync-'+hashlib.sha256(aid.encode()).hexdigest()[:32]);folder.mkdir(parents=True)
    receipt={'status':'unknown','request':request,'request_hash':wire_hash(request)}
    saved={'http_status':200,'attempt_id':aid,'request_hash':wire_hash(request),'response_sha256':'c'*64,
           'response':{'candidates':[{'finishReason':'MAX_TOKENS'}]}}
    if bad=='finish':saved['response']['candidates'][0]['finishReason']='STOP'
    if bad=='request':saved['request_hash']='d'*64
    (folder/'receipt.json').write_text(json.dumps(receipt))
    if bad!='missing':(folder/'provider-response.json').write_text(json.dumps(saved))
    before={p:p.read_bytes() for p in folder.iterdir()}
    with db.uow() as u:
        u.conn.execute("INSERT INTO jobs(id,logical_key,phase,status,created_at,updated_at) VALUES('job','job','analyze','failed','now','now')")
        u.conn.execute("INSERT INTO attempts(id,job_id,attempt_seq,request_hash,status,body,created_at,updated_at,remote_id) VALUES('attempt','job',1,?,'unknown','{}','now','now',?)",(wire_hash(request),'operation' if bad=='remote' else None))
        u.conn.execute("INSERT INTO reservations(id,status,created_at) VALUES('money','reserved','now')")
        u.conn.execute("INSERT INTO capacity_holds VALUES('dispatch','job','fixture',1,'now','unfinished_remote_op')")
    state={'experiment_revision':1,'editorial_v2_'+content_hash(binding)[:16]+'_jobs':[jid]}
    run=SimpleNamespace(id='run',status='paused',stage='quote',experiment_id='exp',state=state)
    adapter=SimpleNamespace(root=root,model='model',prepared=lambda _:None)
    s=SimpleNamespace(db=db,source_evidence=store,providers={'audiovisual_analysis_flashcut':adapter},_current=lambda *args:None)
    auto=SimpleNamespace(s=s,_put=lambda _:None)
    current=json.loads(json.dumps(inputs))
    if bad=='current':current['total_frames']=91
    monkeypatch.setattr('modules.factory.autorun.editorial_recovery.planning_input',lambda *_:(current,binding,evidence))
    review={'reviewer':'QA agent','reviewer_type':'assistant'}
    previous = None
    if bad in ('previous_revision', 'changed_same_revision'):
        previous = store.blobs.put({'binding': {**binding, 'revision': 0 if bad == 'previous_revision' else 1},
                                    'reviewer': 'earlier reviewer'})
        run.state['editorial_local_adoption'] = previous
    if bad and bad != 'previous_revision':
        with pytest.raises(ContractError):adopt_local_plan(auto,run,review)
        assert 'editorial_intent' not in run.state
        assert db.conn.execute('SELECT count(*) FROM capacity_holds').fetchone()[0]==1
    else:
        adopt_local_plan(auto,run,review);manifest=run.state['editorial_intent']
        adopt_local_plan(auto,run,review)
        assert run.state['editorial_intent']==manifest
        assert run.state['editorial_plan_origin']=='local_conservative'
        assert db.conn.execute('SELECT count(*) FROM capacity_holds').fetchone()[0]==0
        if previous:
            assert previous in run.state['editorial_local_adoption_history']
            assert store.blobs.read(previous)['binding']['revision'] == 0
    assert db.conn.execute('SELECT status FROM attempts').fetchone()[0]=='unknown'
    assert db.conn.execute('SELECT status FROM reservations').fetchone()[0]=='reserved'
    assert all(p.read_bytes()==data for p,data in before.items())
    db.close()
