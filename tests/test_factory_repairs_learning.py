import pytest
from modules.factory.analytics.service import ReadbackService
from modules.factory.integrations.publisher import UploadPostPublisher
from modules.factory.learning.service import LearningService
from test_factory_learning import db,_experiment,_policy,_publish,_rich
from modules.factory.domain.errors import ContractError


def test_upload_contract_uses_native_async_fields_and_platform_results():
    sent=[]
    def transport(req):
        sent.append(req)
        if req['method']=='POST':return {'status':202,'body':{'request_id':'stable','status':'processing'}}
        return {'status':200,'body':{'request_id':'stable','status':'completed','results':[
            {'platform':'youtube','success':True,'video_id':'video123','post_url':'https://youtu.be/video123','upload_timestamp':'2026-09-17T12:00:00Z'},
            {'platform':'tiktok','success':False,'error':'failed'}]}}
    client=UploadPostPublisher(api_key='fixture',user='account',transport=transport)
    client.upload(video_url='https://media.invalid/video.mp4',platforms=['youtube'],idempotency_key='stable',schedule_date='2026-10-01T12:00:00Z')
    assert sent[0]['fields']['video']=='https://media.invalid/video.mp4'
    assert sent[0]['fields']['scheduled_date']=='2026-10-01T12:00:00Z'
    assert sent[0]['fields']['request_id']=='stable' and sent[0]['fields']['async_upload']=='true'
    assert client.status('stable')['status']=='public'
    assert sent[-1]['path']=='/api/uploadposts/status?request_id=stable'
    assert client.status('stable',platform='tiktok')['status']=='failed'


def test_weighted_metrics_require_denominators():
    svc=ReadbackService(None,None)
    raw={'analytics':{'columns':['day','views','averageViewDuration'],'rows':[['a',1,100],['b',99,10]]}}
    assert svc._extract(raw,'analytics','averageViewDuration')[0]==pytest.approx(10.9)
    raw={'reach':{'columns':['day','video_thumbnail_impressions','video_thumbnail_impressions_ctr'],'rows':[['a',1,90],['b',99,10]]}}
    assert svc._extract(raw,'reach','video_thumbnail_impressions_ctr')[0]==pytest.approx(10.8)
    raw['reach']['rows'][1][1]=None
    assert svc._extract(raw,'reach','video_thumbnail_impressions_ctr')[0] is None


def test_exposure_required_for_each_arm_no_views_fallback(db):
    _experiment(db);svc=LearningService(db);_policy(svc,min_exposure=100)
    _publish(db,'exp-1',{'a':_rich(1000,10000),'b':_rich(9000,1),'c':_rich(1000,10000),'d':_rich(1000,10000)})
    assert svc.decide('exp-1',1)['conclusion']=='insufficient_exposure'


def test_policy_horizon_cannot_be_overridden(db):
    _experiment(db);svc=LearningService(db);_policy(svc)
    with pytest.raises(ContractError,match='frozen_horizon'):
        svc.decide('exp-1',1,horizon='7d')

from test_factory_publishing import _svc as pubsvc,_auth,_plan,SHA,NOW
from modules.factory.testing.fakes import FakePublisher,FakeAnalytics
from modules.factory.publishing.service import PublishingService
from modules.factory.analytics.client import FactoryAnalyticsClient


def test_wrong_file_empty_accounts_and_manual_declaration_cannot_publish(db,tmp_path):
    svc=pubsvc(db);_auth(db);_plan(svc)
    p=tmp_path/'different.mp4';p.write_bytes(b'different bytes')
    with pytest.raises(ContractError,match='final_bytes_changed'):svc.publish('pub-1',video_path=p,now=NOW)
    assert not svc.fixture_remote.sent
    with pytest.raises(ContractError,match='unknown_account'):_plan(PublishingService(db))
    p=svc.register_manual('manual-unverified',variant_plan_id='vp-x',final_sha256=SHA,platform='youtube',account_id='acct-main',remote_post_id='unverified',published_at=NOW,verify=False)
    assert p.status=='unverified' and not p.published_at
    with pytest.raises(ContractError,match='publication_not_public'):ReadbackService(db,None).due(p.id)


def test_missing_reach_days_and_midnight_mismatch_are_not_complete(db):
    from test_factory_analytics import _publication,T48
    _publication(db)
    fake=FakeAnalytics(reach_rows=[['2026-09-11',30000,5]])
    svc=ReadbackService(db,FactoryAnalyticsClient(transport=fake.transport))
    snap=svc.collect('pub-1','48h',now=T48)
    assert snap.completeness=='partial'
    assert snap.actual_coverage['metrics']['views']['complete']
    assert not snap.actual_coverage['metrics']['thumbnail_ctr']['complete']
    assert snap.timezone=='America/Los_Angeles'
    p=json.loads(db.uow().records.get('publication','pub-1')['body']);p['published_at']='2026-09-10T08:05:00Z'
    with db.uow() as u:u.conn.execute("UPDATE records SET body=? WHERE kind='publication' AND id='pub-1'",(json.dumps(p),))
    fake.reach_rows=[['2026-09-10',10,5],['2026-09-11',10,5],['2026-09-12',10,5]]
    fake.analytics_rows.append(['2026-09-12',17,55,1,1,1,500])
    snap=svc.collect('pub-1','48h',now=T48)
    assert snap.completeness=='partial' and snap.missing_reason=='source_calendar_not_exact_horizon'


def test_current_decisions_and_numeric_revision_order(db):
    _experiment(db);svc=LearningService(db);_policy(svc,promote_min_independent_experiments=3)
    _publish(db,'exp-1',{'a':_rich(1000),'b':_rich(1400),'c':_rich(900),'d':_rich(800)})
    first=svc.decide('exp-1',1)
    original=db.uow().records.get('decision',first['id'])['body']
    from modules.factory.domain.records import MetricSnapshot
    for i in range(12):
        row=db.uow().records.get('metricsnapshot','snap-pub-exp-1-b-48h');body=json.loads(row['body'])
        body['metrics']['views']=1500+i;body['revision']=row['revision']+1
        with db.uow() as u:u.records.put(MetricSnapshot(**body))
        current=svc.decide('exp-1',1)
    assert current['id'].endswith('-v12')
    assert svc.decide('exp-1',1)['_idempotent']
    assert db.uow().records.get('decision',first['id'])['body']==original
    assert svc.promote('fmt-1',min_independent=1)['status']=='promising'
    row=db.uow().records.get('metricsnapshot','snap-pub-exp-1-b-48h');body=json.loads(row['body']);body['metrics']['views']=1;body['revision']=row['revision']+1
    with db.uow() as u:u.records.put(MetricSnapshot(**body))
    assert svc.promote('fmt-1')['independent_experiments']==0


def test_reporting_job_pagination_csv_filter_and_url_guard():
    calls=[]
    def transport(r):
        calls.append(r['url']);url=r['url']
        if url.endswith('/jobs'):return {'body':{'jobs':[],'nextPageToken':'next'}}
        if 'pageToken=next' in url:return {'body':{'jobs':[{'id':'reach','reportTypeId':'channel_reach_basic_a1'}]}}
        if url.endswith('/reports'):return {'body':{'reports':[{'id':'r1','downloadUrl':'https://youtubereporting.googleapis.com/v1/media/r1'}]}}
        return {'body':'date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n20260910,c,chosen,100,5\n20260910,c,other,999,90\n'}
    client=FactoryAnalyticsClient(transport=transport)
    result=client.thumbnail_reach('chosen','2026-09-10','2026-09-11')
    assert result['rows']==[['2026-09-10',100,5]] and len(calls)==4
    from modules.factory.analytics.client import AnalyticsTransportError
    client.transport=lambda r:{'body':{'jobs':[{'id':'reach','reportTypeId':'channel_reach_basic_a1'}]} if r['url'].endswith('/jobs') else {'reports':[{'downloadUrl':'http://127.0.0.1/secret'}]}}
    with pytest.raises(AnalyticsTransportError,match='untrusted_report_url'):client.thumbnail_reach('v','2026-09-10','2026-09-11')


def test_legacy_missing_metrics_never_create_win():
    from modules.analytics.verdict import verdict
    from modules.factory.analytics.compat import legacy_window
    cfg={'win_views_multiplier':2,'win_avd_ratio':.5}
    assert verdict({'views':10000,'avg_view_duration_s':20},30,0,cfg)=='pending'
    assert verdict(legacy_window({'metrics':{},'availability':{}}),30,100,cfg)=='pending'

import json

from test_factory_application import application


def test_public_production_publication_readback_decision_journey(application):
    from test_factory_application import test_application_four_outputs_review_delivery as finish_fixture
    from datetime import datetime,timedelta,timezone
    from zoneinfo import ZoneInfo
    import time
    s,c,act,w,root=application
    finish_fixture(application) # Real API imports, worker renders, reviews and verified fake delivery.
    published=(datetime.now(ZoneInfo('America/Los_Angeles'))+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    remote=FakePublisher(now_fn=lambda:published.isoformat())
    remote.default_steps=['processing','public']
    s.publishing.publisher=UploadPostPublisher(transport=remote.transport,verifier=remote.verify_post)
    s.publishing.accounts={'youtube:acct-main':'acct-main'};s.publishing.max_per_day=4
    analytics=FakeAnalytics()
    for rows in (analytics.analytics_rows,analytics.reach_rows):
        for i,row in enumerate(rows):row[0]=(published+timedelta(days=i)).date().isoformat()
    s.readback=ReadbackService(s.db,FactoryAnalyticsClient(transport=analytics.transport),clock=lambda:(published+timedelta(hours=49)).isoformat())
    r=act('post','/api/experiments/fixture-exp/policy',dict(reviewer='fixture-operator',policy_version='policy-1',horizon='48h',primary_metric='views',min_exposure=100,practical_lift=.3),rev=1)
    assert r.status_code==201,r.text
    ids=[]
    for variant in s.experiment_results('fixture-exp')['variants']:
        final=variant['final'];checks=[r['id'] for r in s.collection('reviews') if r['target_hash']==final['sha256'] and r['verdict']=='pass']
        r=act('post',f"/api/variants/{variant['id']}/publications",dict(platform='youtube',account_id='acct-main',metadata={'title':'Fixture '+variant['variant_key']},check_ids=checks,reviewer='fixture-operator'),rev=1)
        assert r.status_code==201,r.text
        p=r.json()['publication'];ids.append(p['id'])
        r=act('post',f"/api/publications/{p['id']}/authorize",dict(final_sha256=final['sha256'],platform='youtube',account_id='acct-main',action='publish',reviewer='fixture-operator',valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
        assert r.status_code==200,r.text
        r=act('post',f"/api/publications/{p['id']}/run",{});assert r.status_code==202,r.text
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            out=w.tick()
            if out:assert out.get('status') not in ('blocked','failed'),out
            if s.publishing.get(p['id'])['status']=='public':break
            time.sleep(.05)
        assert s.publishing.get(p['id'])['status']=='public'
        # Different observed view totals, common coverage/exposure/definitions.
        analytics.analytics_rows[0][-1]=1400 if variant['variant_key']=='B' else 500
        analytics.analytics_rows[1][-1]=1400 if variant['variant_key']=='B' else 500
        r=act('post',f"/api/publications/{p['id']}/readbacks",{'horizon':'48h'});assert r.status_code==202,r.text
        out=w.tick();assert out['snapshot']['completeness']=='complete',out
    assert remote.public_post_count()==4
    r=act('post','/api/experiments/fixture-exp/decisions',{},rev=1);assert r.status_code==202,r.text
    result=w.tick()['decision'];assert result['conclusion']=='provisional_winner' and result['winner']=='B'
    assert s.readback.compare(ids,'48h')['comparable']
