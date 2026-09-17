import copy
from modules.factory.discovery.cohort import build_cohort
from modules.factory.discovery.evaluate import evaluate


def source():
    return {'post_id':'seed','platform':'youtube','creator_id':'alice','handle':'alice','format':'short','views':1000000,'followers':10000,'published_at':'2026-09-10T00:00:00Z','observed_at':'2026-09-17T00:00:00Z'}


def history():
    return [{**source(),'post_id':f'prior-{i}','views':20000,'published_at':f'2026-08-{i+1:02d}T00:00:00Z'} for i in range(20)]


def test_baseline_excludes_creator_duplicates_future_and_missing_identity():
    seed=source();rows=history()
    rows += [{**rows[0],'post_id':'bob','creator_id':'bob','views':1},dict(rows[0]),
             {**rows[0],'post_id':'future','observed_at':'2026-10-01T00:00:00Z'},
             {**rows[0],'post_id':'unknown','creator_id':None},seed]
    cohort=build_cohort(seed,rows)
    assert cohort['size']==20
    assert cohort['median_views']==20000
    assert {'different_creator','duplicate_post','future_observation','missing_creator','is_seed'} <= {x['reason'] for x in cohort['excluded']}
    assert cohort['available'] and len(cohort['observations'])==20


def test_small_or_unidentified_baseline_is_unavailable_not_a_score():
    seed=source();cohort=build_cohort(seed,history()[:2]);r=evaluate(seed,cohort,mode='baseline')
    assert r['baseline_multiple'] is None and not r['selected']
    assert cohort['median_views'] is None and cohort['observed_median_views']==20000
    seed.pop('creator_id');assert not build_cohort(seed,history())['available']

from datetime import datetime,timedelta,timezone
import json
import pytest
from test_factory_application import application
from modules.factory.providers.synchronous import SynchronousAdapter
from modules.factory.domain.errors import ContractError


class Research(SynchronousAdapter):
    account='fixture-research-account'
    def price(self,request):
        return dict(kind='native_quote',unit='viral_outliers_credits',amount=1,reserve_amount=1,
                    rate_basis='Fixture search tariff, one credit per request',valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    def execute(self,request):
        return {'posts':[source()] if request['kind']=='search' else history()},None,{'actual_credits':1}


def research_plan(application):
    s,c,act,w,root=application
    s.providers['viral_outliers']=Research(root/'receipts')
    r=act('post','/api/research/plans',{'requests':[
        {'kind':'search','query':'clothing','page':1,'page_size':20},
        {'kind':'creator_history','query':'','handle':'alice','platforms':['youtube'],'page':1,'page_size':100}]})
    assert r.status_code==201,r.text
    return r.json()['plan']


def test_public_research_plan_budget_worker_and_replay(application):
    s,c,act,w,root=application
    plan=research_plan(application)
    assert plan['total']=={'viral_outliers_credits':2}
    r=act('post','/api/budgets',{'id':'fixture-research','unit':'viral_outliers_credits','scope':'provider','scope_key':'viral_outliers','ceiling':2,'reviewer':'operator','evidence':'offline fixture grant'})
    assert r.status_code==201,r.text
    approval={'reviewer':'operator','plan_hash':plan['plan_hash'],'ceilings':plan['total'],
              'valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'budget_ids':['fixture-research']}
    r=act('post',f"/api/research/plans/{plan['id']}/authorize",approval);assert r.status_code==200,r.text
    auth=r.json()['authorization_id']
    r=act('post',f"/api/research/plans/{plan['id']}/run",{'authorization_id':auth});assert r.status_code==202,r.text
    jobs=r.json()['jobs'];assert len(jobs)==2
    for _ in jobs:
        out=w.tick();assert out['status']=='succeeded',out
    again=act('post',f"/api/research/plans/{plan['id']}/run",{'authorization_id':auth});assert again.json()['jobs']==jobs
    assert w.tick() is None
    r=act('post','/api/research/evaluate',{'plan_ids':[plan['id']],'policy':{'mode':'baseline'}});assert r.status_code==202,r.text
    out=w.tick();assert out['status']=='complete',out
    run=out['discovery'];assert run['candidates'][0]['baseline_multiple']==50
    assert len(run['cohort']['youtube:seed']['observations'])==20
    assert len(list((root/'receipts').glob('sync-*/receipt.json')))==2
    from modules.factory.budget import BudgetService
    assert BudgetService(s.db).available('fixture-research')==0
    assert s.collection('budgets')[0]['available']==0


def test_public_research_no_funded_scope_cannot_submit(application):
    s,c,act,w,root=application;plan=research_plan(application)
    r=act('post',f"/api/research/plans/{plan['id']}/authorize",dict(reviewer='operator',plan_hash=plan['plan_hash'],ceilings=plan['total'],valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
    assert r.status_code==200,r.text
    act('post',f"/api/research/plans/{plan['id']}/run",{'authorization_id':r.json()['authorization_id']})
    out=w.tick();assert out['error']=='budget_required'
    assert not list((root/'receipts').glob('sync-*'))


def test_effect_plan_rejects_secrets_before_persistence(application):
    s,c,act,w,root=application;s.providers['viral_outliers']=Research(root/'receipts')
    with pytest.raises(ContractError,match='sensitive_request'):
        s.effect_work.prepare('research','viral_outliers','search',[{'api_key':'private-value'}])
    assert not s.collection('research')
