"""Release regressions through the application and real OS worker deaths."""
import copy,json,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from test_factory_application import application,prepare,quote_and_run
from modules.factory.domain.errors import ContractError
from modules.factory.testing.durable import DiskGeneration,CrashDrive
from modules.factory.providers.catalog import CapabilityCatalog,CapabilitySnapshot,snapshot_id


def catalog(s,root, support='observed'):
    s.providers['jimeng_canvas']=DiskGeneration(root)
    CapabilityCatalog(s.db).put(CapabilitySnapshot(schema_version='capability_snapshot.v1',id=snapshot_id('jimeng_canvas','fixture-fast','','text'),created_at=datetime.now(timezone.utc).isoformat(),provider='jimeng_canvas',model='fixture-fast',input_mode='text',support=support,capabilities=s.providers['jimeng_canvas'].capabilities('fixture-fast'),valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))


def generated_plan(application,qualified=True):
    s,c,act,w,root=application;body,_=prepare(application)
    s.providers['jimeng_canvas']=DiskGeneration(root)
    if qualified:catalog(s,root)
    body['id']='generated';body['provider_policy']={'choice':'jimeng','allowed_models':{'jimeng_canvas':['fixture-fast']}}
    for segs in [body['segments']]+[v['segments'] for v in body['variants']]:
        for seg in segs:seg['picture']={'request':{'prompt':'own product '+seg['id'],'model':'fixture-fast','settings':{'resolution':'180x320','aspect':'9:16'}}}
    r=act('post','/api/experiments',body);assert r.status_code==201,r.text
    r=act('post','/api/experiments/generated/quote',{},rev=1);assert r.status_code==202,r.text
    return w.tick()


def test_actual_production_quote_requires_route_evidence(application):
    result=generated_plan(application,False)
    assert result['error']=='capability_evidence_required'
    s,*_=application
    assert not s.db.conn.execute('SELECT 1 FROM attempts').fetchone()


def test_actual_production_dispatch_rechecks_live_qualification(application):
    s,c,act,w,root=application;result=generated_plan(application);plan=result['plan']
    fund_generation(act,plan)
    s.production.router.live=True
    r=act('post','/api/experiments/generated/run',{},rev=1);assert r.status_code==202,r.text
    w.tick();out=w.tick()
    assert out['error']=='route_not_qualified',out
    assert not list((root/'fake-generation').glob('*.json'))


def fund_generation(act,plan):
    r=act('post','/api/budgets',{'id':'credits','unit':'jimeng_credits','scope':'provider','scope_key':'jimeng_canvas','ceiling':10,'reviewer':'fixture','evidence':'offline budget'});assert r.status_code==201,r.text
    r=act('post','/api/experiments/generated/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'fixture','ceilings':{'jimeng_credits':10},'budget_ids':['credits'],'account':'fixture-account','allowed_providers':['jimeng_canvas'],'allowed_models':{'jimeng_canvas':['fixture-fast']},'valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()},rev=1)
    assert r.status_code==200,r.text


def worker(root):
    stream=(root/'worker.log').open('a')
    p=subprocess.Popen([sys.executable,'-m','modules.factory.testing.worker',str(root)],stdout=stream,stderr=stream)
    stream.close();return p


def wait_for(root,predicate,seconds=60):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if predicate():return
        time.sleep(.05)
    pytest.fail('Timed out: '+(root/'worker.log').read_text()[-4000:])


@pytest.mark.parametrize('point',['before_submission','accepted','download','render','upload'])
def test_actual_worker_death_reconciles_without_duplicate_effect(application,point):
    s,c,act,w,root=application;s.delivery.drive=CrashDrive(root)
    if point in ('before_submission','accepted','download'):
        result=generated_plan(application);plan=result['plan'];fund_generation(act,plan)
        r=act('post','/api/experiments/generated/run',{},rev=1);assert r.status_code==202,r.text
        eid='generated'
    else:
        _,art=prepare(application);plan=quote_and_run(application);eid='fixture-exp'
        r=act('post','/api/experiments/fixture-exp/assets/review',{'plan_hash':plan['plan_hash'],'reviewer':'fixture','artifact_ids':[art],'verdict':'pass'},rev=1);assert r.status_code==200,r.text
        if point=='upload':
            for _ in range(30):
                if w.tick() is None:break
            v=s.experiment_results(eid)['variants'][0];final=v['final']
            rev=act('post',f"/api/variants/{v['id']}/reviews",{'check_type':'creative','verdict':'pass','target_hash':final['sha256'],'reviewer':'fixture'}).json()['review']
            r=act('post',f"/api/variants/{v['id']}/deliver",{'folder_id':'folder','account':'offline-drive','reviewer':'fixture','valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'artifact_id':final['artifact_id'],'target_hash':final['sha256'],'check_ids':final['check_ids']+[rev['id']]},rev=1);assert r.status_code==202,r.text
    (root/'fault.json').write_text(json.dumps({'point':point}))
    p=worker(root)
    try:
        wait_for(root,lambda:(root/'fault-reached.json').exists())
        assert p.poll() is None
        p.kill();p.wait(timeout=5)
        (root/'fault-release').touch()
        p=worker(root)
        if point in ('before_submission','accepted','download'):
            def done():return all(n['artifact_ids'] for n in s.production._nodes(plan['id']).values() if n['kind']=='download')
            wait_for(root,done)
            assert len(list((root/'fake-generation').glob('*.json')))==3
            from modules.factory.budget import BudgetService
            assert BudgetService(s.db).available('credits')==7
            assert s.db.conn.execute("SELECT count(*) FROM attempts WHERE status='downloaded'").fetchone()[0]==3
        elif point=='render':
            wait_for(root,lambda:all('final' in v for v in s.experiment_results(eid)['variants']))
            assert len({v['final']['sha256'] for v in s.experiment_results(eid)['variants']})==4
            states=[json.loads(f.read_text()) for f in (root/'data/factory/processes').glob('*.json')]
            assert all(x['status']=='done' for x in states)
        else:
            wait_for(root,lambda:any(x['status']=='verified' and x.get('cleanup_receipt','').startswith('{') for x in s.collection('deliveries')))
            assert len(s.delivery.drive.list_files('folder'))==1
    finally:
        if p.poll() is None:p.terminate();p.wait(timeout=5)
        for v in s.experiment_results(eid)['variants']:s.cleanup.cleanup(v['id'])


def test_restore_activation_retires_old_funding_and_authority(application):
    from modules.factory.operations.backup_restore import create_backup,restore_into
    from modules.factory.operations.reconcile import activate_restore
    from modules.factory.bootstrap import bootstrap
    s,c,act,w,root=application
    act('post','/api/budgets',{'id':'old','unit':'jimeng_credits','scope':'aggregate','scope_key':'','ceiling':100,'reviewer':'fixture','evidence':'before backup'})
    create_backup(s.db,root,root/'backup');restore_into(root/'backup',root/'fresh')
    restored=bootstrap(root/'fresh');at=restored.db.conn.execute("SELECT value FROM meta WHERE key='restore_pending'").fetchone()[0]
    with pytest.raises(ContractError,match='restore_audit_required'):activate_restore(restored.db,restored.artifacts,{})
    result=activate_restore(restored.db,restored.artifacts,{'reviewer':'fixture-auditor','external_audit_reference':'offline no external effects','backup_at':at,'financial_activity_through':datetime.now(timezone.utc).isoformat()})
    assert result['new_funding_required'] and result['new_approvals_required']
    assert restored.db.conn.execute("SELECT 1 FROM meta WHERE key='retired:budget:old'").fetchone()
    assert restored.db.conn.execute("SELECT cap_amount FROM budgets WHERE id='old'").fetchone()[0]==100
    restored.db.close()


def test_offline_auxiliary_never_constructs_live_transport(tmp_path,monkeypatch):
    from modules.factory.providers.configured import configured_auxiliary
    from modules.factory.integrations.http import BoundedHTTP
    monkeypatch.setattr(BoundedHTTP,'__init__',lambda *a,**k:pytest.fail('live transport constructed'))
    assert configured_auxiliary(tmp_path,tmp_path,'offline')==({},None,None,{})


def test_application_elevenlabs_quote_synthesis_fit_review_and_revision(application):
    import base64
    from modules.factory.providers.elevenlabs import ElevenLabsAdapter
    from modules.factory.audio import pcm
    s,c,act,w,root=application;body,_=prepare(application)
    for segs in [body['segments']]+[v['segments'] for v in body['variants']]:
        segs[0]['copy']='hello'
    patch={'segments':body['segments'],'variants':body['variants'],'reason':'add original spoken copy'}
    r=act('patch','/api/experiments/fixture-exp/draft',patch,rev=1);assert r.status_code==200,r.text
    def transport(method,url,payload,headers):
        assert json.loads(payload)['model_id']=='eleven_v3'
        audio=pcm.write_wav(pcm.sine(1,amp=5000))
        return 200,{'x-character-count':'5','request-id':'fixture-v3'},json.dumps({'audio_base64':base64.b64encode(audio).decode(),'alignment':{'characters':list('hello'),'character_start_times_seconds':[i*.2 for i in range(5)],'character_end_times_seconds':[(i+1)*.2 for i in range(5)]}}).encode()
    expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    s.providers['elevenlabs']=ElevenLabsAdapter(root/'tts',transport=transport,account='fixture',pricing={'credits_per_character':1,'valid_until':expiry,'evidence':'fixture tariff'})
    r=act('post','/api/effects/plans',{'kind':'tts','provider':'elevenlabs','model':'eleven_v3','experiment_id':'fixture-exp','requests':[{'text':'hello','voice_id':'fixture','model':'eleven_v3','language':'en','settings':{}}]},rev=2);assert r.status_code==201,r.text
    plan=r.json()['plan'];assert plan['total']=={'elevenlabs_credits':5}
    r=act('post','/api/budgets',{'id':'tts','unit':'elevenlabs_credits','scope':'provider','scope_key':'elevenlabs','ceiling':5,'reviewer':'fixture','evidence':'approved fake synthesis'});assert r.status_code==201,r.text
    auth=act('post',f"/api/effects/plans/{plan['id']}/authorize",{'plan_hash':plan['plan_hash'],'reviewer':'fixture','budget_ids':['tts'],'ceilings':plan['total'],'valid_until':expiry}).json()['authorization_id']
    jobs=act('post',f"/api/effects/plans/{plan['id']}/run",{'authorization_id':auth}).json()['jobs']
    out=w.tick();assert out['status']=='succeeded',out
    r=act('post','/api/experiments/fixture-exp/speech/fit',{'variant_key':'A','segment_id':'s0','job_id':jobs[0]['job_id']},rev=2);assert r.status_code==202,r.text
    fitted=w.tick();assert fitted.get('speech'),fitted
    speech=fitted['speech'];assert speech['duration_s']==1 and fitted['captions']['cues'][0]['end_frame']==30
    r=act('post',f"/api/speech/{speech['id']}/approve",{'reviewer':'fixture','speech_hash':speech['speech_hash']});assert r.status_code==200,r.text
    r=act('post','/api/experiments/fixture-exp/speech/attach',{'speech_ids':[speech['id']]},rev=2);assert r.status_code==200,r.text
    assert s._current('fixture-exp').revision==3
    assert s.experiments._variant('fixture-exp','B').segments[0]['captions'][0]['text']=='Variation B'
    assert s.experiments._variant('fixture-exp','A').segments[0]['speech']['artifact_id']==speech['artifact_id']


def test_nested_invalid_inputs_and_secrets_never_persist(application):
    s,c,act,w,root=application
    r=act('post','/api/experiments',{'blueprint_id':'b','template_id':'t','segments':[{'id':'x','target':[]}],'variants':[{}, {}, {}]})
    assert r.status_code==400 and r.json()['error']=='invalid_command'
    r=act('post','/api/seeds',{'url':'https://youtu.be/abcdefghijk','refresh_token':'fake-sensitive-string'})
    assert r.status_code==400 and 'fake-sensitive-string' not in r.text
    assert not s.collection('seeds')


def test_populated_v7_migration_preserves_intents_and_allows_distinct_explicit_work(tmp_path):
    import sqlite3
    from modules.factory.store import Database
    from modules.factory.store.schema import MIGRATIONS
    path=tmp_path/'version7.db';db=sqlite3.connect(path,isolation_level=None)
    for version,ddl in MIGRATIONS[:7]:
        db.executescript(ddl);db.execute("INSERT OR REPLACE INTO meta VALUES('schema_version',?)",(str(version),))
    body=json.dumps({'original':'preserve exact content'})
    db.execute("INSERT INTO intents VALUES('old','same','generation',?,NULL,'original-remote','dispatched','2026-09-16')",(body,))
    db.execute("INSERT INTO budgets VALUES('old-money','jimeng_credits','aggregate','',100,'2026-09-16')");db.close()
    current=Database(path)
    assert current.conn.execute("SELECT body FROM intents WHERE intent_key='old'").fetchone()[0]==body
    with current.uow() as u:u.intents.create('new','same','generation',{'original':'different approved logical operation'})
    assert current.conn.execute("SELECT count(*) FROM intents WHERE request_hash='same'").fetchone()[0]==2
    assert current.conn.execute("SELECT cap_amount FROM budgets WHERE id='old-money'").fetchone()[0]==100
    current.close()


def test_process_concurrency_holds_five_jimeng_one_vertex_after_worker_death(application):
    s,c,act,w,root=application;body,_=prepare(application,6);catalog(s,root)
    s.providers['google_vertex']=DiskGeneration(root,'google_vertex')
    CapabilityCatalog(s.db).put(CapabilitySnapshot(schema_version='capability_snapshot.v1',id=snapshot_id('google_vertex','fixture-fast','','text'),created_at=datetime.now(timezone.utc).isoformat(),provider='google_vertex',model='fixture-fast',input_mode='text',support='observed',capabilities=s.providers['google_vertex'].capabilities('fixture-fast'),valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
    for provider,eid,unit in [('jimeng_canvas','parallel-jimeng','jimeng_credits'),('google_vertex','parallel-vertex','usd_micros')]:
        b=copy.deepcopy(body);b['id']=eid
        b['provider_policy']={'choice':'jimeng' if provider=='jimeng_canvas' else 'vertex','allowed_models':{provider:['fixture-fast']}}
        segments=[]
        for i in range(6):
            seg=copy.deepcopy(body['segments'][0]);seg.update(id=f's{i}',slot_id=f'slot-{i}',target={'start_frame':i*30,'end_frame':(i+1)*30},picture={'request':{'prompt':eid+str(i),'model':'fixture-fast','settings':{'resolution':'180x320'}}},captions=[{'text':'Original '+str(i),'start_frame':i*30,'end_frame':(i+1)*30}]);segments.append(seg)
        b['segments']=segments;b['variants']=[]
        for i,key in enumerate('BCD'):
            segs=copy.deepcopy(segments);segs[i]['captions'][0]['text']='Variant '+key
            b['variants'].append({'key':key,'factor':'hook','regions':[segments[i]['target']],'segments':segs,'hypothesis':'test','primary_metric':'retention','allowed_fields':['captions']})
        assert act('post','/api/experiments',b).status_code==201
        assert act('post',f'/api/experiments/{eid}/quote',{},rev=1).status_code==202
        plan=w.tick()['plan']
        assert act('post','/api/budgets',{'id':eid,'unit':unit,'scope':'provider','scope_key':provider,'ceiling':6,'reviewer':'fixture','evidence':'fake parallel scope'}).status_code==201
        r=act('post',f'/api/experiments/{eid}/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'fixture','ceilings':{unit:6},'budget_ids':[eid],'account':'fixture-account','allowed_providers':[provider],'allowed_models':{provider:['fixture-fast']},'valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()},rev=1);assert r.status_code==200,r.text
    for eid in ('parallel-jimeng','parallel-vertex'):
        assert act('post',f'/api/experiments/{eid}/run',{},rev=1).status_code==202
    w.tick();w.tick()  # persist both DAGs before starting workers
    (root/'hold-remote').touch();children=[worker(root) for _ in range(6)]
    try:
        wait_for(root,lambda:len(list((root/'fake-generation').glob('*.json')))==5 and len(list((root/'fake-vertex').glob('*.json')))==1)
        for p in children:p.kill();p.wait(timeout=5)
        time.sleep(1.2)
        children=[worker(root)]
        time.sleep(1.5)
        snapshot=s.scheduler.status_snapshot()['capacities']
        assert snapshot['jimeng_submit']['used']==5 and snapshot['vertex_submit']['used']==1
        assert len(list((root/'fake-generation').glob('*.json')))==5
        assert len(list((root/'fake-vertex').glob('*.json')))==1
        (root/'hold-remote').unlink()
        wait_for(root,lambda:s.db.conn.execute("SELECT count(*) FROM attempts WHERE status='downloaded'").fetchone()[0]==12)
        assert len(list((root/'fake-generation').glob('*.json')))==6
        assert len(list((root/'fake-vertex').glob('*.json')))==6
    finally:
        for p in children:
            if p.poll() is None:p.terminate();p.wait(timeout=5)


def test_public_vertex_analysis_uses_real_media_and_durable_receipt(application):
    import base64
    from modules.factory.analysis.vertex import VertexAnalyzer
    from modules.factory.providers.vertex_auth import VertexAuth
    s,c,act,w,root=application;prepare(application)
    seed=s.collection('seeds')[0];calls=[]
    result={'beats':[{'id':'whole','start_s':0,'end_s':3,'role':'body','confidence':'uncertain','visual_event':'moving fixture'}], 'transcript':[],'music':{'role':'none'}}
    def transport(method,url,payload,headers):
        body=json.loads(payload);raw=base64.b64decode(body['contents'][0]['parts'][0]['inlineData']['data'])
        assert raw==(root/'source.mp4').read_bytes()
        assert headers['Authorization']=='Bearer private-fixture-token'
        calls.append(url)
        return 200,{},json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(result)}]}}],'usageMetadata':{'totalTokenCount':42}}).encode()
    expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    auth=VertexAuth(lambda:{'kind':'oauth','access_token':'private-fixture-token','project':'fixture','identity':'fixture','scopes':['cloud-platform']},'fixture')
    s.providers['audiovisual_analysis']=VertexAnalyzer(root/'analysis',s.artifacts,auth,'fixture','fixture','fixture-analysis',{'estimate_usd_micros':1,'reserve_usd_micros':2,'evidence':'fixture','valid_until':expiry},transport=transport)
    r=act('post',f"/api/seeds/{seed['id']}/analysis/prepare",{'model':'fixture-analysis'});assert r.status_code==201,r.text
    plan=r.json()['plan']
    act('post','/api/budgets',{'id':'analysis','unit':'usd_micros','scope':'aggregate','scope_key':'','ceiling':2,'reviewer':'fixture','evidence':'fake only'})
    approved=act('post',f"/api/effects/plans/{plan['id']}/authorize",{'plan_hash':plan['plan_hash'],'reviewer':'fixture','budget_ids':['analysis'],'ceilings':plan['total'],'valid_until':expiry});assert approved.status_code==200,approved.text
    r=act('post',f"/api/effects/plans/{plan['id']}/run",{'authorization_id':approved.json()['authorization_id']});assert r.status_code==202,r.text
    job=r.json()['jobs'][0]['job_id'];done=w.tick();assert done['status']=='succeeded',done
    assert not done['charge_verified']
    r=act('post',f"/api/seeds/{seed['id']}/analysis/collect",{'job_id':job,'reviewer':'fixture'});assert r.status_code==202,r.text
    out=w.tick();assert out['blueprint']['provenance']['analyzer']=='audiovisual_analysis',out
    assert out['blueprint']['beats'][0]['confidence']=='uncertain'
    assert len(calls)==1
    assert 'private-fixture-token' not in ''.join(p.read_text() for p in (root/'analysis').rglob('*.json'))


def test_reporting_ambiguous_setup_matches_exact_name(tmp_path):
    from modules.factory.providers.reporting import ReportingSetup
    from modules.factory.execution.context import dispatch_context
    from modules.factory.testing.fakes import ProviderError
    class Client:
        calls=0
        jobs=[]
        def create_reach_job(self,name):
            self.calls+=1;self.jobs=[{'id':'wrong','name':'other'},{'id':'right','name':name}]
            raise ProviderError('response_lost')
        def reach_jobs(self):return self.jobs
    client=Client();adapter=ReportingSetup(tmp_path,client,'fixture')
    with dispatch_context({'attempt_id':'one'}):
        with pytest.raises(ProviderError):adapter.submit({'name':'exact','report_type':'channel_reach_basic_a1'})
        result=adapter.reconcile()
    assert result['status']=='succeeded' and result['result']['job']['id']=='right'
    assert client.calls==1


def test_worker_transfer_retry_is_bounded_and_local_retry_cannot_replace_paid_attempt(application):
    from modules.factory.testing.fakes import ProviderError
    from modules.factory.services.recovery import retry_local
    s,c,act,w,root=application
    job=s.commands.enqueue('fixture-transfer',{},phase='collect')['job_id']
    def broken(*args):raise ProviderError('download_transport_failed',transient=True)
    w.execute=broken
    for i in range(6):
        s.db.conn.execute('UPDATE jobs SET next_attempt_at=NULL WHERE id=?',(job,))
        result=w.tick();assert result['status']==('retry' if i<5 else 'failed')
    assert s.db.uow().jobs.get(job)['retry_count']==6
    with pytest.raises(ContractError,match='retries_exhausted'):retry_local(s,job,'fixture')


def test_public_reporting_setup_requires_explicit_zero_budget_and_deduplicates(application):
    from modules.factory.providers.reporting import ReportingSetup
    s,c,act,w,root=application
    class Reporting:
        calls=0
        def create_reach_job(self,name):self.calls+=1;return {'id':'job-native','name':name,'reportTypeId':'channel_reach_basic_a1'}
    client=Reporting();s.providers['youtube_reporting']=ReportingSetup(root/'reporting',client,'fixture-account')
    r=act('post','/api/analytics/reporting/prepare',{'name':'factory reach','reviewer':'fixture'});assert r.status_code==201,r.text
    plan=r.json()['plan'];expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    request={'plan_hash':plan['plan_hash'],'reviewer':'fixture','budget_ids':['zero'],'ceilings':{'usd_micros':0},'valid_until':expiry}
    r=act('post',f"/api/effects/plans/{plan['id']}/authorize",request);assert r.status_code==400
    act('post','/api/budgets',{'id':'zero','unit':'usd_micros','scope':'aggregate','scope_key':'','ceiling':0,'reviewer':'fixture','evidence':'read-only account setup'})
    r=act('post',f"/api/effects/plans/{plan['id']}/authorize",request);assert r.status_code==200,r.text
    auth=r.json()['authorization_id']
    for _ in range(2):
        r=act('post',f"/api/effects/plans/{plan['id']}/run",{'authorization_id':auth});assert r.status_code==202,r.text
    out=w.tick();assert out['status']=='succeeded' and out['charge_verified'],out
    assert client.calls==1 and w.tick() is None


def test_restore_cli_preserves_populated_artifacts_and_quarantines_old_processes(application,capsys):
    from modules.factory.cli import main
    from modules.factory.store import Database
    s,c,act,w,root=application;prepare(application)
    original=s.collection('assets');assert original
    s.resources.register('source-process',4321,'fixture-birth','fixture-command','fixture-owner')
    assert main(['--root',str(root),'backup',str(root/'backup')])==0
    assert main(['--root',str(root),'restore',str(root/'backup'),str(root/'fresh')])==3
    from modules.factory.bootstrap import bootstrap
    restored=bootstrap(root/'fresh')
    try:
        assert restored.resources.get('source-process')['pid']==0
        assert restored.resources.get('source-process')['status']=='not_owned_after_restore'
        assert s.resources.get('source-process')['pid']==4321
        originals=json.loads((root/'fresh/data/factory/restore-evidence/original-resources.json').read_text())
        assert json.loads(originals[0]['body'])['pid']==4321
        assert restored._current('fixture-exp').content_hash==s._current('fixture-exp').content_hash
        for art in original:assert restored.artifacts.verified_path(art['id']).is_file()
        assert main(['--root',str(root/'fresh'),'gate'])==1
    finally:restored.db.close()
    capsys.readouterr()


def test_public_terminal_generation_manual_replacement_resumes_downstream(application):
    from modules.factory.testing.fakes import ProviderError
    s,c,act,w,root=application;out=generated_plan(application);plan=out['plan'];fund_generation(act,plan)
    def rejected(request,**kwargs):raise ProviderError('rejected_before_accept')
    s.providers['jimeng_canvas'].submit=rejected
    act('post','/api/experiments/generated/run',{},rev=1);w.tick();w.tick()
    failed=s.db.conn.execute("SELECT id FROM jobs WHERE experiment_id='generated' AND status='failed'").fetchone();assert failed
    node=s.detail('workitem',failed['id']);artifact=s.collection('seeds')[0]['source_asset_id']
    r=act('post','/api/experiments/generated/assets/replace',{'plan_hash':plan['plan_hash'],'node_key':node['node_key'],'artifact_id':artifact,'reviewer':'fixture'},rev=1);assert r.status_code==200,r.text
    assert s.db.uow().jobs.get(failed['id'])['status']=='succeeded'
    download=s.db.uow().jobs.get(plan['id']+':dl:'+node['request_hash']);assert download['status']=='succeeded'
    review=s.db.uow().jobs.get(plan['id']+':rev:'+node['request_hash'])
    assert review is None or review['status'] in ('waiting_dependencies','ready')
    assert len(list((root/'fake-generation').glob('*.json')))==0


def test_drive_upload_checks_native_current_account_and_exact_grant(tmp_path):
    from types import SimpleNamespace
    from modules.factory.integrations.drive import GdriveCLI
    from modules.factory.execution.context import dispatch_context
    calls=[]
    def runner(argv,**kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0,stdout='other@example.invalid\n')
    drive=GdriveCLI(runner=runner,expected_account='approved@example.invalid')
    with pytest.raises(ContractError,match='delivery_account_scope_mismatch'):
        drive.upload('folder',tmp_path/'video.mp4','final.mp4')
    assert not calls
    with dispatch_context({'provider':'drive','account':'approved@example.invalid'}):
        with pytest.raises(RuntimeError,match='drive_account_mismatch'):drive.upload('folder',tmp_path/'video.mp4','final.mp4')
    assert calls==[['gdrive','account','current']]
