import json
import pytest
from modules.factory.domain.errors import ContractError
from modules.factory.testing.fakes import ProviderError


def request():
    return {'task':'prioritize_evidence','model':'jev-1.13.0','rubric':'optional_evidence.v1',
            'binding':{'source_sha256':'a'*64,'evidence_sha256':'b'*64,'transcript_sha256':'c'*64},
            'candidates':[{'id':'audio:1','summary':'Spectral onset at 1.2s; no speech nearby.', 'mandatory':False},
                          {'id':'opening','summary':'Opening coverage.', 'mandatory':True}]}


def adapter(tmp_path, transport):
    from modules.factory.analysis.jev import JevDecisions
    return JevDecisions(tmp_path, credentials=lambda:{'TYPESAFE_API_KEY':'fake-test-key'},
         transport=transport, account='test-account', pricing={'input_usd_micros_per_million':42000,
             'valid_until':'2099-01-01T00:00:00Z','evidence':'offline-pricing-fixture'})


def test_jev_is_text_only_pinned_and_validates_candidate_bindings(tmp_path):
    calls=[]
    def transport(method,url,body,headers):
        native=json.loads(body)
        calls.append(native)
        assert native['model']=='jev-1.13.0'
        assert native['state']['candidates']==request()['candidates']
        assert set(native['questions'])=={'audio:1'}
        return 200,{},json.dumps({'model':'jev-1.13.0','answers':{'audio:1':{
            'type':'choice','choice':'retain','probabilities':{'retain':.95,'optional':.05},'confidence':.9}},
            'usage':{'input_tokens':100,'output_tokens':20}}).encode()
    route=adapter(tmp_path,transport)
    price=route.price(request())
    result=route.submit(request())
    assert result['status']=='succeeded' and price['reserve_amount']>0
    assert result['result']['decisions']=={'audio:1':'retain'}
    assert route.submit(request())['operation_id']==result['operation_id'] and len(calls)==1


def test_unknown_jev_submission_is_not_retried_or_erased(tmp_path):
    calls=[]
    def timeout(*args):
        calls.append(1)
        raise TimeoutError('lost acknowledgement')
    route=adapter(tmp_path,timeout)
    with pytest.raises(ProviderError,match='jev_timeout'):
        route.submit(request())
    assert adapter(tmp_path,timeout).submit(request())['status']=='unknown'
    assert len(calls)==1


def test_jev_rejects_foreign_identity_and_unbounded_or_visual_inputs(tmp_path):
    def wrong(*args):
        return 200,{},json.dumps({'model':'jev-1.13.0','answers':{'invented':{}},'usage':{}}).encode()
    route=adapter(tmp_path,wrong)
    with pytest.raises(ProviderError,match='malformed_jev_response'):
        route.submit(request())
    assert route.submit(request())['status']=='unknown'
    invalid=request();invalid['candidates'][0]['embedding']=[1,2,3]
    with pytest.raises(ContractError,match='invalid_jev_candidate'):
        route.price(invalid)
    invalid=request();invalid['candidates'][0]['summary']='x'*40000
    with pytest.raises(ContractError,match='invalid_jev_candidate'):
        route.price(invalid)


def test_shadow_and_fallback_never_drop_mandatory_coverage():
    from modules.factory.analysis.jev import select_evidence
    candidates=request()['candidates']
    assert select_evidence(candidates,{'audio:1':'optional'},mode='shadow')==['audio:1','opening']
    assert select_evidence(candidates,None,mode='active',benchmark={'qualified':True})==['audio:1','opening']
    with pytest.raises(ContractError,match='jev_active_unqualified'):
        select_evidence(candidates,{'audio:1':'optional'},mode='active')
    proof={'qualified':True,'mandatory_loss':0,'benefit_observed':True,'evidence_sha256':'d'*64}
    assert select_evidence(candidates,{'audio:1':'optional'},mode='active',benchmark=proof)==['opening']


def test_jev_uses_normal_reservation_and_unknown_is_not_replayed(tmp_path):
    from modules.factory.bootstrap import bootstrap
    from modules.factory.budget import BudgetService
    from modules.factory.services.worker import ApplicationWorker
    calls=[]
    def timeout(*args):
        calls.append(1)
        raise TimeoutError()
    s=bootstrap(tmp_path/'app')
    try:
        route=adapter(tmp_path/'jev',timeout)
        s.providers['jev_decisions']=route
        budget=BudgetService(s.db)
        budget.create_budget('qa-jev','usd_micros','aggregate',cap=0)
        plan=s.effect_work.prepare('analysis','jev_decisions',route.model,[request()])
        body={'plan_hash':plan['plan_hash'],'reviewer':'offline-test','ceilings':plan['total'],
              'budget_ids':['qa-jev'],'valid_until':'2099-01-01T00:00:00Z'}
        auth=s.effect_work.authorize(plan['id'],body)
        queued=s.effect_work.queue(plan['id'],auth['authorization_id'])
        worker=ApplicationWorker(s)
        out=worker.tick()
        assert out.get('error')=='reservation_blocked' and calls==[]
        # A distinct test plan has independent authority; no failed/unknown job
        # is reset to obtain that authority.
        budget.create_budget('qa-jev','usd_micros','aggregate',cap=100000)
        plan=s.effect_work.prepare('analysis','jev_decisions',route.model,[request()])
        auth=s.effect_work.authorize(plan['id'],{**body,'plan_hash':plan['plan_hash']})
        queued=s.effect_work.queue(plan['id'],auth['authorization_id'])
        worker.tick()
        attempt=s.effect_work._latest_attempt(queued['jobs'][0]['job_id'])
        assert attempt['status']=='unknown' and len(calls)==1
        held=s.db.conn.execute('SELECT status FROM reservations WHERE id=?',(attempt['reservation_id'],)).fetchone()
        assert held[0] in ('held','ambiguous')
        # Durable adapter observation does not re-enter transport.
        from modules.factory.execution.context import dispatch_context
        with dispatch_context({'attempt_id':attempt['id']}):
            assert route.reconcile(request_hash=attempt['request_hash'])['status']=='unknown'
        assert len(calls)==1
    finally:
        s.db.close()
