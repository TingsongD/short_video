"""Reviewed citations change only cited frames, never reported timing or facts."""
from copy import deepcopy
import pytest
from test_factory_flashcut_point_cuts import sample
from modules.factory.domain.errors import ContractError
from modules.factory.testing.fakes import ProviderError


def reviewed():
    request,value=sample()
    request['media'].append({'id':'frame:65','kind':'image','source_time':'13/6'})
    value['observations'][0]['evidence_ids']=['window:0','frame:64','frame:65']
    review={'reviewer_type':'assistant','reviewer':'visual QA',
            'corrections':[{'observation_id':'cut','before_frame_id':'frame:63','after_frame_id':'frame:64',
                            'before_description':'Entrance aisle.', 'after_description':'Seafood counter.'}]}
    return request,value,review


def test_reviewed_cut_keeps_original_and_validates_complete_answer():
    from modules.factory.analysis.cut_review import apply_cut_review
    request,value,review=reviewed();before=deepcopy(value)
    result=apply_cut_review(value,request,review)
    assert value==before
    assert result['observations'][0]['start_s']==2.1
    assert result['observations'][0]['end_s']==64/30
    assert result['cut_citation_review']['original_observations']==before['observations']
    assert result['cut_citation_review']['reviewer_type']=='assistant'


@pytest.mark.parametrize('bad',['foreign','same_frame','time','kind','gap','missing','extra_invalid','reviewer','duplicate'])
def test_review_cannot_override_other_validation(bad):
    from modules.factory.analysis.cut_review import apply_cut_review
    request,value,review=reviewed();o=value['observations'][0];c=review['corrections'][0]
    if bad=='foreign':c['before_frame_id']='frame:62'
    if bad=='same_frame':c['before_frame_id']='frame:64'
    if bad=='time':o.update(start_s=2.12,end_s=2.12)
    if bad=='kind':o['kind']='action'
    # The reviewed window covers [0,4): a gap must overlap supplied media
    # to be invalid. Wholly external gaps are retained as source context.
    if bad=='gap':value['coverage_gaps']=[{'start_s':3.9,'end_s':8}]
    if bad=='missing':value['essential_missing']=['invented']
    if bad=='extra_invalid':value['observations'].append({**o,'id':'other','kind':'action','end_s':1})
    if bad=='reviewer':review['reviewer_type']='automatic_human'
    if bad=='duplicate':review['corrections'].append(deepcopy(c))
    with pytest.raises((ContractError,ProviderError)):apply_cut_review(value,request,review)


def test_review_retains_external_gap_without_claiming_window_coverage():
    from modules.factory.analysis.cut_review import apply_cut_review
    request,value,review=reviewed()
    value['coverage_gaps']=[{'start_s':4,'end_s':8}]
    result=apply_cut_review(value,request,review)
    assert result['out_of_scope_coverage_gaps']==value['coverage_gaps']
    assert result['cut_citation_review']['original_observations']==value['observations']


def test_bound_review_is_restart_safe_and_retains_unknown_money(tmp_path):
    import hashlib,json
    from types import SimpleNamespace
    from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer
    from modules.factory.autorun.cut_review import CutReview
    from modules.factory.store import Database
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from modules.factory.execution.effects import wire_hash
    request,value,review=reviewed()
    request.update(task='analyze_flashcut',model='gemini-3.8-flash',binding={'source_sha256':'a'*64})
    attempt='attempt'; job='job'
    review.update(job_id=job,attempt_id=attempt,provider_response_sha256='b'*64)
    adapter=FlashcutAnalyzer.__new__(FlashcutAnalyzer)
    adapter.root=tmp_path/'provider';adapter.model=request['model']
    checks=[];adapter.prepared=lambda q:checks.append(deepcopy(q))
    folder=adapter.root/('sync-'+hashlib.sha256(attempt.encode()).hexdigest()[:32]);folder.mkdir(parents=True)
    (folder/'receipt.json').write_text(json.dumps({'request':request,'request_hash':wire_hash(request),'status':'unknown'}))
    (folder/'provider-response.json').write_text(json.dumps({'http_status':200,'attempt_id':attempt,
        'request_hash':wire_hash(request),'response_sha256':'b'*64,
        'response':{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]}}))
    originals={p:p.read_bytes() for p in folder.iterdir()}
    db=Database(tmp_path/'db')
    with db.uow() as u:
        u.conn.execute("INSERT INTO jobs(id,logical_key,phase,status,created_at,updated_at) VALUES('job','job','analyze','failed','now','now')")
        u.conn.execute("INSERT INTO attempts(id,job_id,attempt_seq,request_hash,status,body,created_at,updated_at) VALUES('attempt','job',1,?,'unknown','{}','now','now')",(wire_hash(request),))
        u.conn.execute("INSERT INTO reservations(id,status,created_at) VALUES('money','reserved','now')")
        u.conn.execute("INSERT INTO capacity_holds VALUES('dispatch','job','fixture',1,'now','unfinished_remote_op')")
    store=SourceEvidenceService(db,tmp_path/'evidence')
    plan=store.blobs.put({'requests':[request,{}]})
    run=SimpleNamespace(id='run',status='paused',stage='video_analysis',state={
        'flashcut_format_recovery':plan,'flashcut_format_0_jobs':['job']})
    auto=SimpleNamespace(s=SimpleNamespace(db=db,providers={'audiovisual_analysis_flashcut':adapter},source_evidence=store))
    recovery=CutReview(auto);recovery.enable(run,review)
    first=recovery.collect(run,request,job)
    assert first['observations'][0]['start_s']==2.1
    restarted=SimpleNamespace(**{**vars(run),'state':deepcopy(run.state)})
    assert CutReview(auto).collect(restarted,request,job)==first
    assert db.conn.execute('SELECT count(*) FROM capacity_holds').fetchone()[0]==0
    assert db.conn.execute('SELECT status FROM reservations').fetchone()[0]=='reserved'
    assert db.conn.execute('SELECT status FROM attempts').fetchone()[0]=='unknown'
    assert all(p.read_bytes()==b for p,b in originals.items())
    changed={**review,'reviewer':'different reviewer'}
    with pytest.raises(ContractError,match='cut_review_changed'):recovery.enable(run,changed)
    with pytest.raises(ContractError,match='cut_review_unproven'):
        recovery.enable(run,{**review,'provider_response_sha256':'c'*64})
    (folder/'provider-response.json').write_text('{}')
    with pytest.raises(ContractError):recovery.collect(run,request,job)
    db.close()


def test_review_preserves_structured_gaps_as_pending_evidence():
    from modules.factory.analysis.cut_review import apply_cut_review
    request,value,review=reviewed();request['binding']={'source_sha256':'a'*64}
    value['coverage_gaps']=[{'start_s':4,'end_s':8}]
    result=apply_cut_review(value,request,review,preserve_gaps=True)
    assert result['essential_missing']==['source']
    assert result['coverage_gap_recovery']['claimed_ranges']==[{'start_s':'4','end_s':'8'}]
    assert result['coverage_gap_recovery']['status']=='requires_source_clarification'
    assert result['cut_citation_review']['original_observations']==value['observations']
    value['coverage_gaps']=[{'start_s':4,'end_s':9}]
    with pytest.raises(ContractError):apply_cut_review(value,request,review,preserve_gaps=True)


@pytest.mark.parametrize('bad',[None,'source','hash','missing','conflict'])
def test_supplement_is_bound_to_frozen_sibling_request(bad):
    from modules.factory.autorun.cut_review import supplement_request
    from modules.factory.execution.effects import wire_hash
    request,value,review=reviewed();request['binding']={'source_sha256':'a'*64}
    sibling=deepcopy(request);request['media']=[m for m in request['media'] if m['id']!='frame:63']
    review['supplemental_request_hash']=wire_hash(sibling)
    if bad=='source':request['binding']={'source_sha256':'b'*64}
    if bad=='hash':review['supplemental_request_hash']='c'*64
    if bad=='missing':sibling['media']=[m for m in sibling['media'] if m['id']!='frame:63'];review['supplemental_request_hash']=wire_hash(sibling)
    if bad=='conflict':sibling['media'][0]['source_end']='5';review['supplemental_request_hash']=wire_hash(sibling)
    before=deepcopy(request);verified=[]
    if bad:
        with pytest.raises(ContractError):supplement_request(request,review,[sibling],lambda q:verified.append(q))
    else:
        effective,supplement=supplement_request(request,review,[sibling],lambda q:verified.append(q))
        assert [m['id'] for m in supplement['media']]==['frame:63']
        assert any(m['id']=='frame:63' for m in effective['media'])
        assert verified==[sibling]
    assert request==before


def test_multiple_supplements_verify_each_exact_source_and_reject_duplicates():
    from modules.factory.autorun.cut_review import supplement_request
    from modules.factory.execution.effects import wire_hash
    request,value,review=reviewed();request['binding']={'source_sha256':'a'*64}
    one=deepcopy(request);two=deepcopy(request)
    one['media']=[m for m in one['media'] if m['id']!='frame:64']
    two['media']=[m for m in two['media'] if m['id']!='frame:63']
    request['media']=[m for m in request['media'] if m['kind']=='video']
    review['supplemental_request_hashes']=[wire_hash(one),wire_hash(two)]
    verified=[]
    effective,evidence=supplement_request(request,review,[one,two],lambda q:verified.append(q))
    assert {m['id'] for m in evidence['media']}=={'frame:63','frame:64'}
    assert verified==[one,two]
    review['supplemental_request_hashes']*=2
    with pytest.raises(ContractError):supplement_request(request,review,[one,two],lambda _:None)


def test_prior_review_sources_require_same_run_and_evidence(tmp_path):
    from modules.factory.autorun.cut_review import frozen_review_requests
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from modules.factory.store import Database
    db=Database(tmp_path/'db');store=SourceEvidenceService(db,tmp_path/'evidence')
    request,_,_=reviewed();other=deepcopy(request);other['scope']='whole'
    prior={'run_id':'r','binding':{'source_sha256':'a'*64},'original_plan_identity':'original','requests':[other,request]}
    plan={'run_id':'r','binding':prior['binding'],'original_plan_identity':'original','requests':[request,{}],
          'prior_plan':store.blobs.put(prior)}
    assert frozen_review_requests(store,plan)==[request,other]
    prior['run_id']='foreign';plan['prior_plan']=store.blobs.put(prior)
    with pytest.raises(ContractError):frozen_review_requests(store,plan)
    db.close()
