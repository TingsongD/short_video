"""Permanent regression tests for the 2026-09-17 post-repair review.

Each test asserts the REPAIRED contract for findings N01-N20 from
docs/factory-reports/REVIEW-POST-REPAIR-2026-09-17.md. The original
defect-reproduction probes remain at
docs/factory-reports/probes/review_post_repair_2026_09_17.py as an audit
trail; the probe→test mapping lives in docs/factory-reports/REPAIRS.md.
"""
import base64
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from test_factory_application import application, prepare, quote_and_run
from test_factory_repairs_release import generated_plan, fund_generation

from modules.factory.domain.errors import ContractError
from modules.factory.testing.fakes import ProviderError


# ----------------------------------------------------------------- N01 --

def test_withdrawn_acceptance_blocks_publication(application):
    """N01: a queued publication revalidates creative acceptance before
    the external effect — a withdrawn verdict must stop it."""
    from test_factory_application import test_application_four_outputs_review_delivery
    from modules.factory.testing.fakes import FakePublisher
    from modules.factory.integrations.publisher import UploadPostPublisher
    test_application_four_outputs_review_delivery(application)
    s,c,act,w,root=application
    remote=FakePublisher();s.publishing.publisher=UploadPostPublisher(transport=remote.transport,verifier=remote.verify_post)
    s.publishing.accounts={'youtube:acct-main':'acct-main'}
    r=act('post','/api/experiments/fixture-exp/policy',dict(reviewer='fixture-operator',policy_version='policy-1',horizon='48h',primary_metric='views',min_exposure=100,practical_lift=.3),rev=1);assert r.status_code==201,r.text
    variant=s.experiment_results('fixture-exp')['variants'][0];final=variant['final']
    checks=[r['id'] for r in s.collection('reviews') if r['target_hash']==final['sha256'] and r['verdict']=='pass']
    r=act('post',f"/api/variants/{variant['id']}/publications",dict(platform='youtube',account_id='acct-main',metadata={'title':'Fixture'},check_ids=checks,reviewer='fixture-operator'),rev=1);assert r.status_code==201,r.text
    p=r.json()['publication']
    r=act('post',f"/api/publications/{p['id']}/authorize",dict(final_sha256=final['sha256'],platform='youtube',account_id='acct-main',action='publish',reviewer='fixture-operator',valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()));assert r.status_code==200,r.text
    r=act('post',f"/api/publications/{p['id']}/run",{});assert r.status_code==202,r.text
    r=act('post',f"/api/variants/{variant['id']}/reviews",dict(check_type='creative',verdict='fail',target_hash=final['sha256'],reviewer='fixture-operator'));assert r.status_code==201,r.text
    with pytest.raises(ContractError,match='acceptance_blocked'):
        s.quality.accept(s.artifacts.verified_path(final['artifact_id']),checks,final['binding'])
    out=w.tick()
    assert not remote.sent,out


# ----------------------------------------------------------------- N02 --

def test_failed_result_fails_job_and_releases_hold(application):
    """N02: an unrecognized/failed handler result marks the job failed —
    never succeeded — and the local_work hold is released."""
    s,c,act,w,root=application
    body,art=prepare(application);plan=quote_and_run(application)
    r=act('post','/api/experiments/fixture-exp/assets/review',{'plan_hash':plan['plan_hash'],'reviewer':'fixture-operator','artifact_ids':[art],'verdict':'pass'},rev=1)
    assert r.status_code==200,r.text
    def failed(*args,**kwargs):raise RuntimeError('simulated ffmpeg failure')
    s.rendering.fast.render=failed
    for _ in range(30):
        result=w.tick()
        if result and result.get('status')=='failed':break
    assert result['status']=='failed',result
    row=s.db.uow().jobs.get(result['job_id'])
    assert row['status']=='failed',row
    assert not s.db.conn.execute('SELECT value FROM meta WHERE key=?',('local_work:'+row['id'],)).fetchone()


# ----------------------------------------------------------------- N03 --

def test_reconcile_resumes_failed_production(application):
    """N03: when reconciliation proves the remote effect succeeded, the
    failed production job resumes instead of stranding descendants."""
    s,c,act,w,root=application
    plan=generated_plan(application)['plan']; fund_generation(act,plan)
    adapter=s.providers['jimeng_canvas']; original=adapter.submit
    def lost(request,price=None):
        original(request,price)
        raise ProviderError('response_lost')
    adapter.submit=lost
    act('post','/api/experiments/generated/run',{},rev=1); w.tick()
    failed=w.tick(); jid=failed['job_id']
    adapter.submit=original
    assert s.db.uow().jobs.get(jid)['status']=='failed'
    r=act('post',f'/api/jobs/{jid}/reconcile',{})
    out=w.tick()
    assert out['attempts'][0]['status']=='succeeded',out
    assert out['resumed'] is True
    assert s.db.uow().jobs.get(jid)['status'] in ('ready','waiting_dependencies','succeeded')


# ------------------------------------------------------------- N04/N05 --

def test_canvas_quote_flush_preserves_concurrent_receipts(tmp_path):
    """N04: prepare_quote's merge-write cannot lose a receipt another
    worker durably saved during the quote window."""
    from modules.assets.canvas_cli import CanvasCLI
    from modules.factory.providers.canvas import CanvasAdapter
    from modules.factory.providers.state import DurableState
    from modules.factory.testing.fakes import FakeCanvasRunner
    from test_factory_repairs_protocols import REQ
    file=tmp_path/'state.json';cli=CanvasCLI(runner=FakeCanvasRunner(tmp_path/'remote.json'))
    adapter=CanvasAdapter(cli,DurableState(file));quote=cli.quote
    def concurrent_quote(*args):
        other=DurableState(file)
        with other.locked():
            other['ops']['other-worker']={'operation_id':'other-worker','status':'accepted'};other.flush()
        return quote(*args)
    cli.quote=concurrent_quote
    adapter.prepare_quote(REQ)
    assert 'other-worker' in DurableState(file)['ops']


def test_canvas_attempts_get_distinct_operations(tmp_path):
    """N05: two durable executor attempts never share one remote
    generation, even for an identical request."""
    from modules.assets.canvas_cli import CanvasCLI
    from modules.factory.providers.canvas import CanvasAdapter
    from modules.factory.domain.money import Money
    from modules.factory.testing.fakes import FakeCanvasRunner
    from modules.factory.execution.context import dispatch_context
    from test_factory_repairs_protocols import REQ
    runner=FakeCanvasRunner(tmp_path/'remote.json');a=CanvasAdapter(CanvasCLI(runner=runner),{})
    with dispatch_context({'attempt_id':'first'}):one=a.submit(REQ,price=Money('jimeng_credits',54))
    with dispatch_context({'attempt_id':'second'}):two=a.submit(REQ,price=Money('jimeng_credits',54))
    assert one['operation_id']!=two['operation_id'] and len(runner.doc['ops'])==2


# ------------------------------------------------------------- N06/N12 --

def test_vertex_recovers_saved_acceptance_by_attempt(tmp_path):
    """N06: reconcile consults the attempt-scoped submission first — a
    locally saved acceptance survives an adapter restart."""
    from modules.factory.providers.vertex import VertexAdapter
    from modules.factory.providers.vertex_auth import VertexAuth
    from modules.factory.providers.state import DurableState
    from modules.factory.testing.fakes import FakeOAuthLoader,FakeVertexTransport
    from modules.factory.execution.context import dispatch_context
    from modules.factory.execution.effects import wire_hash
    from test_factory_vertex import RATES,CAPS,REQ
    loader=FakeOAuthLoader(tmp_path/'oauth.json');transport=FakeVertexTransport(tmp_path/'remote.json',loader)
    a=VertexAdapter(VertexAuth(loader,'factory-proj'),transport,DurableState(tmp_path/'adapter.json'),RATES,capabilities=CAPS)
    with dispatch_context({'attempt_id':'original-attempt'}):op=a.submit(REQ)
    restarted=VertexAdapter(VertexAuth(loader,'factory-proj'),transport,DurableState(tmp_path/'adapter.json'),RATES,capabilities=CAPS)
    with dispatch_context({'attempt_id':'original-attempt'}):recovered=restarted.reconcile(request_hash=wire_hash(REQ))
    assert recovered is not None and recovered['operation_id']==op['operation_id']


def test_vertex_nested_settings_applied_and_conflicts_rejected(tmp_path):
    """N12: nested settings.aspect/resolution reach the transport;
    contradictory top-level+nested values are a hard conflict."""
    from modules.factory.providers.vertex import VertexAdapter
    from modules.factory.providers.vertex_auth import VertexAuth
    from modules.factory.testing.fakes import FakeOAuthLoader
    from test_factory_vertex import RATES,CAPS,REQ
    caps=copy.deepcopy(CAPS)
    caps[REQ['model']]['aspects']=['9:16','16:9'];caps[REQ['model']]['resolutions']=['720p','1080p']
    a=VertexAdapter(VertexAuth(FakeOAuthLoader(tmp_path/'auth'),'factory-proj'),lambda *x:None,{},RATES,capabilities=caps)
    request=dict(REQ,settings={'aspect':'16:9','resolution':'1080p'});request.pop('aspect',None);request.pop('resolution',None)
    video=a._payload(request,request['model'])['response_format'][0]
    assert video['aspect_ratio']=='16:9' and video['resolution']=='1080p'
    conflict=dict(REQ,aspect='9:16',settings={'aspect':'16:9'})
    with pytest.raises(ProviderError,match='conflicting_settings'):
        a._payload(conflict,conflict['model'])


# ----------------------------------------------------------------- N07 --

@pytest.mark.parametrize('normalize_before_submit',[False,True])
def test_tts_normalized_copy_fits_and_attaches(application,normalize_before_submit):
    """N07: ordinary copy fits after paid synthesis and the approved
    speech actually attaches with normalized-copy provenance."""
    from modules.factory.providers.elevenlabs import ElevenLabsAdapter
    from modules.factory.audio import pcm
    s,c,act,w,root=application;body,_=prepare(application)
    for segs in [body['segments']]+[v['segments'] for v in body['variants']]:segs[0]['copy']="It's 2 dollars."
    r=act('patch','/api/experiments/fixture-exp/draft',{k:body[k] for k in ('segments','variants')},rev=1);assert r.status_code==200,r.text
    text=s.audio_work.speech.normalize(body['segments'][0]['copy']) if normalize_before_submit else body['segments'][0]['copy']
    def transport(method,url,payload,headers):
        n=len(text);audio=pcm.write_wav(pcm.sine(1,amp=5000))
        return 200,{'x-character-count':str(n),'request-id':'fixture'},json.dumps({'audio_base64':base64.b64encode(audio).decode(),'alignment':{'characters':list(text),'character_start_times_seconds':[i/n for i in range(n)],'character_end_times_seconds':[(i+1)/n for i in range(n)]}}).encode()
    expiry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    s.providers['elevenlabs']=ElevenLabsAdapter(root/'tts',transport=transport,account='fixture',pricing={'credits_per_character':1,'valid_until':expiry,'evidence':'fixture tariff'})
    r=act('post','/api/effects/plans',{'kind':'tts','provider':'elevenlabs','model':'eleven_v3','experiment_id':'fixture-exp','requests':[{'text':text,'voice_id':'fixture','model':'eleven_v3','language':'en','settings':{}}]},rev=2);assert r.status_code==201,r.text
    plan=r.json()['plan']
    r=act('post','/api/budgets',{'id':'tts','unit':'elevenlabs_credits','scope':'provider','scope_key':'elevenlabs','ceiling':len(text),'reviewer':'fixture','evidence':'approved fake synthesis'});assert r.status_code==201,r.text
    r=act('post',f"/api/effects/plans/{plan['id']}/authorize",{'plan_hash':plan['plan_hash'],'reviewer':'fixture','budget_ids':['tts'],'ceilings':plan['total'],'valid_until':expiry});assert r.status_code==200,r.text
    jobs=act('post',f"/api/effects/plans/{plan['id']}/run",{'authorization_id':r.json()['authorization_id']}).json()['jobs']
    out=w.tick();assert out['status']=='succeeded',out
    r=act('post','/api/experiments/fixture-exp/speech/fit',{'variant_key':'A','segment_id':'s0','job_id':jobs[0]['job_id']},rev=2)
    assert r.status_code==202,r.text
    out=w.tick();assert out.get('speech'),out
    speech=out['speech']
    r=act('post',f"/api/speech/{speech['id']}/approve",{'reviewer':'fixture','speech_hash':speech['speech_hash']});assert r.status_code==200,r.text
    r=act('post','/api/experiments/fixture-exp/speech/attach',{'speech_ids':[speech['id']]},rev=2);assert r.status_code==200,r.text
    attached=s.experiments._variant('fixture-exp','A').segments[0]['speech']
    assert attached['normalized_copy']==s.audio_work.speech.normalize("It's 2 dollars.")


# ----------------------------------------------------------------- N08 --

def test_treatment_stale_derived_media_flagged():
    """N08: a copy change carrying byte-identical derived media is a
    defect — declaration of dependent fields is not proof of update."""
    from modules.factory.experiments.diff import check_treatment
    segment={'id':'a','target':{'start_frame':0,'end_frame':30},'copy':'Old copy','speech':{'artifact_id':'old'},'captions':[],'picture':{'artifact_id':'old-picture'}}
    control={'segments':[segment]};variant=copy.deepcopy(control);variant['segments'][0]['copy']='Entirely new copy'
    problems=check_treatment(control,variant,[segment['target']],['copy','speech','captions','picture'],[])
    assert any(p['flag']=='stale_derived_media' for p in problems)


# ----------------------------------------------------------------- N09 --

def test_delivery_reentry_delegates_to_retry(application):
    """N09: re-entering deliver() on an intent with no attempt delegates
    to transfer-only retry — never an infinite pending loop."""
    s,c,act,w,root=application
    src=root/'review-fixture.mp4';src.write_bytes(b'fixture bytes for transfer-only identity')
    drive=s.delivery.drive;original=drive.list_files
    def failed(parent):raise RuntimeError('temporary listing outage')
    drive.list_files=failed
    with pytest.raises(RuntimeError):s.delivery.deliver('review-delivery',src,'review.mp4','folder')
    assert not s.delivery._get('review-delivery').get('attempt_id')
    drive.list_files=original
    called=[];real=s.delivery.retry
    s.delivery.retry=lambda *a,**k:called.append(1) or {'status':'pending','action':'retry_transfer'}
    s.delivery.deliver('review-delivery',src,'review.mp4','folder')
    assert called


# ----------------------------------------------------------------- N10 --

def test_runner_retry_executes_fresh_attempt(tmp_path):
    """N10: an orphaned old-format receipt is never replayed as a new
    attempt's result — the runner executes."""
    from modules.factory.store import Database
    from modules.factory.resources.runner import OwnedRunner
    from modules.factory.providers.state import DurableState
    db=Database(tmp_path/'factory.db');runner=OwnedRunner(db,tmp_path/'processes','review')
    argv=[sys.executable,'-c','print("success")'];cwd=str((tmp_path/'processes').resolve())
    identity=hashlib.sha256(json.dumps([argv,cwd,'review']).encode()).hexdigest()
    receipt=DurableState(tmp_path/'processes'/(identity+'.json'))
    receipt.update(status='done',returncode=1,stdout='',stderr='temporary disk error');receipt.flush()
    first=runner(argv)
    assert first.returncode==0
    db.close()


# ----------------------------------------------------------------- N11 --

def test_restore_paths_preserve_render_identity(tmp_path):
    """N11: identical media bytes relocated into a fresh restore root
    keep the same render identity — no false revision mismatch."""
    from modules.factory.store import Database
    from modules.factory.rendering.service import RenderService
    from types import SimpleNamespace
    db=Database(tmp_path/'db');renderer=SimpleNamespace(render=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('interrupted fixture renderer')))
    render=RenderService(db,None,tmp_path/'renders',fast_renderer=renderer)
    render.register('build',{'id':'comp','content_hash':'hash','variant_key':'A','renderer':'ffmpeg_fast'},now=datetime.now(timezone.utc).isoformat())
    old=tmp_path/'old-media';new=tmp_path/'fresh-restored-media';old.write_bytes(b'identical fixture media');new.write_bytes(old.read_bytes())
    first=render.dispatch('build',[{'src':str(old)}],[],[],{})
    assert first['status']=='failed'
    second=render.dispatch('build',[{'src':str(new)}],[],[],{})
    assert second['status']=='failed',second


# ----------------------------------------------------------------- N13 --

def test_canvas_typed_reference_contract(tmp_path):
    """N13: router-format typed references take the typed contract path
    — ProviderError, never an AttributeError crash."""
    from modules.assets.canvas_cli import CanvasCLI
    from modules.factory.providers.canvas import CanvasAdapter
    from modules.factory.testing.fakes import FakeCanvasRunner
    from test_factory_repairs_protocols import REQ
    a=CanvasAdapter(CanvasCLI(runner=FakeCanvasRunner(tmp_path/'remote.json')), {})
    with pytest.raises(ProviderError,match='reference_artifact_required'):
        a.prepare({**REQ,'refs':[{'kind':'image','artifact_id':'registered-product'}]})


# ----------------------------------------------------------------- N14 --

def test_still_images_pass_production_qc(application):
    """N14: image artifacts in the authorized plan are intentional
    stills — the composition passes technical QC with still evidence."""
    import subprocess
    s,c,act,w,root=application;body,_=prepare(application)
    image=root/'product.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=180x320','-frames:v','1',str(image)],check=True)
    r=act('post','/api/imports',content=image.read_bytes(),headers={'x-filename':'product.png'});assert r.status_code==201,r.text
    art=r.json()['artifact']['id']
    for segs in [body['segments']]+[v['segments'] for v in body['variants']]:
        for seg in segs:seg['picture']={'artifact_id':art}
    r=act('patch','/api/experiments/fixture-exp/draft',{k:body[k] for k in ('segments','variants')},rev=1);assert r.status_code==200,r.text
    r=act('post','/api/experiments/fixture-exp/quote',{},rev=2);assert r.status_code==202,r.text
    plan=w.tick()['plan']
    r=act('post','/api/experiments/fixture-exp/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'fixture-operator'},rev=2);assert r.status_code==200,r.text
    r=act('post','/api/experiments/fixture-exp/run',{},rev=2);assert r.status_code==202,r.text
    for _ in range(40):
        if w.tick() is None:break
    r=act('post','/api/experiments/fixture-exp/assets/review',{'plan_hash':plan['plan_hash'],'reviewer':'fixture-operator','artifact_ids':[art],'verdict':'pass'},rev=2);assert r.status_code==200,r.text
    for _ in range(40):
        out=w.tick()
        if out is None:break
    final=s.experiment_results('fixture-exp')['variants'][0]['final']
    review=s.quality._get(final['check_ids'][0])
    assert review['verdict']=='pass',review
    assert review['evidence_data']['expected']['intentional_stills']


# ----------------------------------------------------------------- N15 --

def test_production_render_uses_frozen_mix(application):
    """N15: production audio is pre-mixed through the revision-frozen
    MixService profile — loudness evidence rides on the final."""
    from test_factory_application import test_application_four_outputs_review_delivery
    test_application_four_outputs_review_delivery(application)
    s,c,act,w,root=application
    final=s.experiment_results('fixture-exp')['variants'][0]['final']
    assert final['mix']['profile_hash'] and final['mix']['measured']
    assert final['mix']['artifact_id'] and 'clipped' in final['mix']
    exp=s._current('fixture-exp')
    profile=s.mix.get(f"mix-fixture-exp-r{exp.revision}")
    assert profile['status']=='frozen' and profile['profile_hash']==final['mix']['profile_hash']


# ----------------------------------------------------------------- N16 --

def test_authorization_uses_pinned_snapshot(application):
    """N16: authorization validates against the packaged snapshot
    revision — a later Shopify refresh cannot rewrite approved facts."""
    from modules.factory.domain.records import ProductSnapshot
    s,c,act,w,root=application;body,_=prepare(application)
    snap=ProductSnapshot(schema_version='product_snapshot.v1',id='snapshot',created_at=datetime.now(timezone.utc).isoformat(),shop='fixture',product_id='gid://shopify/Product/1',title='Product',pagination_complete=True,claims=[{'text':'Cotton'}])
    with s.db.uow() as u:u.records.put(snap)
    body['id']='pinned-product';body['product_ids']=['snapshot']
    for segs in [body['segments']]+[v['segments'] for v in body['variants']]:segs[0]['claims']=['Cotton']
    r=act('post','/api/experiments',body);assert r.status_code==201,r.text
    assert s._current('pinned-product').packaging['products'][0]['revision']==0
    assert act('post','/api/experiments/pinned-product/quote',{},rev=1).status_code==202
    plan=w.tick()['plan']
    snap.revision=1;snap.claims=[{'text':'Polyester'}]
    with s.db.uow() as u:u.records.put(snap)
    r=act('post','/api/experiments/pinned-product/authorize',{'reviewer':'operator','plan_hash':plan['plan_hash']},rev=1)
    assert r.status_code==200,r.text


# ----------------------------------------------------------------- N17 --

def test_variant_claims_are_validated(application):
    """N17: claims on treatment variants face the same product evidence
    as the control — invented claims block authorization."""
    s,c,act,w,root=application;body,art=prepare(application)
    body['id']='unsupported-claim'
    body['variants'][0]['segments'][0]['claims']=['Invented product certification']
    body['variants'][0]['allowed_fields'].append('claims')
    r=act('post','/api/experiments',body);assert r.status_code==201,r.text
    assert act('post','/api/experiments/unsupported-claim/quote',{},rev=1).status_code==202
    plan=w.tick()['plan']
    r=act('post','/api/experiments/unsupported-claim/authorize',{'reviewer':'operator','plan_hash':plan['plan_hash']},rev=1)
    assert r.status_code==400 and 'unsupported_claim' in r.text,r.text


# ----------------------------------------------------------------- N18 --

def test_research_cache_and_truthful_coverage(application):
    """N18: identical research requests hit the durable cache instead of
    re-charging, and coverage reports real provider calls."""
    from test_factory_repairs_research import research_plan
    s,c,act,w,root=application
    r=act('post','/api/budgets',{'id':'research','unit':'viral_outliers_credits','scope':'provider','scope_key':'viral_outliers','ceiling':4,'reviewer':'operator','evidence':'offline fixture grant'});assert r.status_code==201,r.text
    plan_ids=[]
    for _ in range(2):
        plan=research_plan(application);plan_ids.append(plan['id'])
        r=act('post',f"/api/research/plans/{plan['id']}/authorize",{'reviewer':'operator','plan_hash':plan['plan_hash'],'ceilings':plan['total'],'valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'budget_ids':['research']});assert r.status_code==200,r.text
        act('post',f"/api/research/plans/{plan['id']}/run",{'authorization_id':r.json()['authorization_id']})
        for _ in range(2):
            out=w.tick();assert out['status']=='succeeded',out
    act('post','/api/research/evaluate',{'plan_ids':[plan_ids[0]],'policy':{'mode':'baseline'}})
    assert w.tick()['status']=='complete'
    run=s.collection('research')[0]
    assert run['coverage']['actual_calls']==2 and run['coverage']['planned_pages']==2 and run['coverage']['received_pages']==2
    assert s.db.conn.execute('SELECT count(*) FROM discovery_cache').fetchone()[0]==2
    assert len(list((root/'receipts').glob('sync-*/receipt.json')))==2


# ----------------------------------------------------------------- N19 --

def test_new_revision_policy_not_blocked_by_old_posts(tmp_path):
    """N19: publications from an older revision never gate a new
    revision's policy freeze; publication lookup is revision-scoped."""
    from test_factory_learning import _experiment,_policy,_publish,_rich
    from modules.factory.store import Database
    from modules.factory.learning.service import LearningService
    from modules.factory.domain.records import ExperimentRevision,VariantPlan
    db=Database(tmp_path/'db');_experiment(db);svc=LearningService(db)
    _policy(svc);_publish(db,'exp-1',{'a':_rich(1000)})
    original=json.loads(db.uow().records.get('experimentrevision','exp:exp-1')['body'])
    original.update(revision=2,content_hash='revision-two')
    with db.uow() as u:
        u.records.put(ExperimentRevision(**original))
        for key in 'abcd':
            row=json.loads(u.records.get('variantplan','vp-exp-1-'+key)['body']);row.update(revision=2,experiment_revision=2)
            u.records.put(VariantPlan(**row))
    policy=_policy(svc,rev=2)
    assert policy


# ----------------------------------------------------------------- N20 --

def test_readiness_cached_and_refresh_bypasses(application):
    """N20: readiness checks are cached 60s per-process; an explicit
    refresh bypasses the cache."""
    s,c,act,w,root=application
    calls=[]
    class FakeRoute:
        account='fixture'
        def readiness(self):
            calls.append(1);return {'installed':True}
    s.providers['fake-route']=FakeRoute()
    s.providers_readiness();s.providers_readiness()
    assert len(calls)==1
    s.providers_readiness(refresh=True)
    assert len(calls)==2
