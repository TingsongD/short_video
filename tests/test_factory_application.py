"""Public API → durable worker → actual local exports; no fabricated finals."""
import copy
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from modules.factory.bootstrap import bootstrap
from modules.factory.api import create_app
from modules.factory.services.worker import ApplicationWorker
from modules.factory.audio import pcm
from modules.factory.testing.fixtures import _moving_mp4, _png


class FakeHypit:
    """Scripted Hypit transport for tests — offline, no Runtime Profile,
    produces real PNG evidence files and a word-timed transcript."""
    def __init__(self, whisperx=True):
        self.whisperx = whisperx; self.calls = []
    def available(self): return True
    def transcribe_available(self): return self.whisperx
    def paths(self): return {"profileSource": "test"}
    def probe(self, src): return {}
    def boundaries(self, src):
        self.calls.append(("boundaries", str(src)))
        return {"boundaries": [{"t": 1.0, "score": 0.9}]}
    def transcribe(self, src, language, dest):
        self.calls.append(("transcribe", str(src)))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(json.dumps({
            "format": "hypit.transcript@1", "source": str(src),
            "language": language, "audio_seconds": 3.0,
            "passages": [{"text": "dog ball", "start_seconds": 0.0,
                          "end_seconds": 1.0, "words": [
                    {"text": "dog", "start_seconds": 0.0,
                     "end_seconds": 0.4},
                    {"text": "ball", "start_seconds": 0.5,
                     "end_seconds": 1.0}]}]}))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    def tiles(self, src, dest_dir, every, transcript=None, start=None,
              end=None, columns=4, rows=3):
        self.calls.append(("tiles", str(src), start, end))
        d = Path(dest_dir); d.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            _png(d / f"grid-{i}.png")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def complete_deep_analysis(s, act, w, seed, seconds, hypit=None):
    """Drive the mandatory Hypit-directed analysis to 'complete' —
    machine stages via the worker, operator stages + review via API."""
    s.ref_analysis.hypit = hypit or FakeHypit()
    r = act('post', f'/api/seeds/{seed}/analysis', {'reviewer': 'fixture-operator'})
    assert r.status_code == 202, r.text
    out = w.tick()
    assert out and out.get('analysis'), out
    fields = {f: f'{f} reading' for f in
              ('premise', 'progression', 'hook', 'setups', 'payoffs',
               'ending', 'replay_appeal', 'intended_response')}
    fields['observations'] = ['a dog fetches a ball and misses']
    fields['interpretations'] = ['the miss is the joke']
    fields['uncertainties'] = ['whether the bounce was staged']
    r = act('put', f'/api/analysis/{seed}/understanding',
            {'reviewer': 'fixture-operator', **fields})
    assert r.status_code == 200, r.text
    span = seconds / 3
    sections = [{'start_s': i * span, 'end_s': (i + 1) * span,
                 'phase': p, 'summary': f'{p} section'}
                for i, p in enumerate(('hook', 'body', 'payoff'))]
    r = act('put', f'/api/analysis/{seed}/timeline',
            {'reviewer': 'fixture-operator', 'sections': sections})
    assert r.status_code == 200, r.text
    r = act('put', f'/api/analysis/{seed}/treatment',
            {'reviewer': 'fixture-operator',
             **{f: f'{f} note' for f in
                ('summary', 'preserves', 'redesigns',
                 'script_direction')}})
    assert r.status_code == 200, r.text
    r = act('post', f'/api/analysis/{seed}/review',
            {'reviewer': 'fixture-operator', 'verdict': 'accept'})
    assert r.status_code == 200, r.text
    return s.ref_analysis.get(seed)


def seed_completed_analysis(db, seed_id, source_sha256, duration_s=30.0):
    """Insert a complete ReferenceAnalysis record directly (unit tests
    of downstream mechanics that only need the gate satisfied)."""
    from modules.factory.analysis.deep import (
        analysis_id_for, _hash, UNDERSTANDING_FIELDS, TREATMENT_FIELDS)
    from modules.factory.domain.records import ReferenceAnalysis
    from modules.factory.store.uow import utcnow
    a = ReferenceAnalysis(
        schema_version='referenceanalysis.v1',
        id=analysis_id_for(seed_id), created_at=utcnow(), seed_id=seed_id,
        revision=1, status='complete', stage='review',
        stages={s: {'done': True, 'at': utcnow()} for s in
                ('acquire', 'transcript', 'evidence', 'documents')},
        source_asset_id='art-x', source_sha256=source_sha256,
        acquisition={'duration_s': duration_s, 'audio_present': True,
                     'verified_at': utcnow()},
        transcript={'status': 'aligned', 'provider': 'whisperx',
                    'word_count': 2, 'preliminary': False},
        evidence={'boundaries': [{'t': 1.0, 'score': 1}],
                  'grids': [{'artifact_id': 'art-g', 'start_s': 0.0,
                             'end_s': duration_s, 'every_s': 1.0,
                             'transcript_linked': True}],
                  'coverage_s': duration_s},
        understanding={f: 'x' for f in UNDERSTANDING_FIELDS} | {
            'observations': ['o'], 'interpretations': ['i'],
            'uncertainties': []},
        timeline=[{'start_s': 0.0, 'end_s': duration_s, 'phase': 'all',
                   'summary': 'x'}],
        treatment={f: 'x' for f in TREATMENT_FIELDS},
        review={'reviewer': 'qa', 'at': utcnow(), 'verdict': 'accept'})
    a.content_hash = _hash(a)
    with db.uow() as u:
        u.records.put(a)
    return a


class DiskDrive:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(exist_ok=True)
    def list_files(self,parent):
        return [json.loads(p.read_text()) for p in self.root.glob('*.json') if json.loads(p.read_text())['parent']==parent]
    def stat(self,fid):
        p=self.root/(fid+'.json'); return json.loads(p.read_text()) if p.exists() else None
    def upload(self,parent,path,name):
        import hashlib,uuid,shutil
        fid=uuid.uuid4().hex; dest=self.root/(fid+'.mp4'); shutil.copy2(path,dest)
        meta={'id':fid,'name':name,'parent':parent,'size':dest.stat().st_size,'md5':hashlib.md5(dest.read_bytes()).hexdigest()}
        (self.root/(fid+'.json')).write_text(json.dumps(meta)); return {'id':fid}
    def link(self,fid): return 'https://drive.invalid/file/'+fid


@pytest.fixture
def application(tmp_path):
    service=bootstrap(tmp_path,drive=DiskDrive(tmp_path/'remote'),settings={'drive_folder_id':'folder','raise_worker_errors':True})
    client=TestClient(create_app(service,session_token='test-session'))
    seq=[0]
    def action(method,path,body=None,rev=None,**kwargs):
        seq[0]+=1
        headers={'x-csrf-token':'test-session','idempotency-key':kwargs.pop('key',f'action-{seq[0]}')}
        if rev is not None: headers['x-expected-revision']=str(rev)
        headers.update(kwargs.pop('headers',{}))
        result=getattr(client,method)(path,json=body,headers=headers,**kwargs)
        return result
    yield service,client,action,ApplicationWorker(service),tmp_path
    service.db.close()


def prepare(application,seconds=3):
    s,c,act,w,root=application
    src=root/'source.mp4'; _moving_mp4(src,seconds,size='180x320')
    seed=act('post','/api/seeds',{'url':'https://youtu.be/abcdefghijk'}).json()['seed']['seed']['id']
    result=act('post','/api/imports',content=src.read_bytes(),headers={'x-filename':'source.mp4'})
    assert result.status_code==201,result.text
    art=result.json()['artifact']['id']
    r=act('post',f'/api/seeds/{seed}/media',{'artifact_id':art}); assert r.status_code==200,r.text
    span=seconds/3; frames=round(seconds*30); unit=frames//3
    observations={'beats':[{'id':f'b{i}','role':['hook','body','cta'][i],'start_s':i*span,'end_s':(i+1)*span,'confidence':'reviewed','visual_event':'moving product sample'} for i in range(3)],
        'transcript':[{'id':'speech','start_s':0,'end_s':seconds,'text':'Source timing reference'}],'music':{'role':'bed'}}
    r=act('post',f'/api/seeds/{seed}/analyze',{'observations':observations,'reviewer':'fixture-operator'}); assert r.status_code==202,r.text
    out=w.tick(); assert out.get('blueprint'),out
    bp=out['blueprint']
    complete_deep_analysis(s,act,w,seed,seconds)
    r=act('post',f"/api/blueprints/{bp['id']}/review",{'content_hash':bp['content_hash'],'reviewer':'fixture-operator'}); assert r.status_code==200,r.text
    tpl=act('post','/api/templates',{'blueprint_id':bp['id'],'id':'fixture-template'}); assert tpl.status_code==201,tpl.text
    wav=pcm.write_wav(pcm.sine(seconds,amp=6500))
    sound=act('post','/api/imports',content=wav,headers={'x-filename':'licensed-fixture-bed.wav'}).json()['artifact']['id']
    segments=[{'id':f's{i}','slot_id':f'slot-{i}','role':['hook','body','cta'][i], 'target':{'start_frame':i*unit,'end_frame':(i+1)*unit},
            'picture':{'artifact_id':art,'source_in_s':i*span},'speech':{},'copy':'',
            'captions':[{'text':f'Original line {i}','start_frame':i*unit,'end_frame':(i+1)*unit}], 'transition':'cut','claims':[]} for i in range(3)]
    variants=[]
    for i,key in enumerate('BCD'):
        segs=copy.deepcopy(segments); segs[i]['captions'][0]['text']=f'Variation {key}'
        variants.append({'key':key,'factor':['hook','body','ending'][i],'regions':[segments[i]['target']],
            'segments':segs,'hypothesis':'This caption improves retention','primary_metric':'retention','allowed_fields':['captions']})
    body={'id':'fixture-exp','blueprint_id':bp['id'],'template_id':'fixture-template','segments':segments,'variants':variants,
        'music':{'artifact_id':sound,'gain':1,'provenance':'generated local test tone'}}
    r=act('post','/api/experiments',body); assert r.status_code==201,r.text
    return body,art


def quote_and_run(application):
    s,c,act,w,root=application
    r=act('post','/api/experiments/fixture-exp/quote',{},rev=1); assert r.status_code==202,r.text
    quote=w.tick(); assert quote.get('plan'),quote
    plan=quote['plan']
    r=act('post','/api/experiments/fixture-exp/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'fixture-operator'},rev=1); assert r.status_code==200,r.text
    r=act('post','/api/experiments/fixture-exp/run',{},rev=1); assert r.status_code==202,r.text
    assert s.db.uow().jobs.get(r.json()['run']['job_id'])
    for _ in range(40):
        out=w.tick()
        if out is None: break
        assert out.get('status') not in ('blocked','failed'),out
    return plan


def test_application_four_outputs_review_delivery(application):
    s,c,act,w,root=application
    body,art=prepare(application)
    plan=quote_and_run(application)
    assert all('final' not in v for v in s.experiment_results('fixture-exp')['variants'])
    r=act('post','/api/experiments/fixture-exp/assets/review',{'plan_hash':plan['plan_hash'],'reviewer':'fixture-operator','artifact_ids':[art],'verdict':'pass'},rev=1); assert r.status_code==200,r.text
    for _ in range(30):
        out=w.tick()
        if out is None: break
        assert out.get('status') not in ('blocked','failed'),out
    variants=s.experiment_results('fixture-exp')['variants']
    assert len(variants)==4
    assert len({v['final']['sha256'] for v in variants})==4, 'Declared caption treatments must be visible in the actual exports'
    assert len(s.collection('seeds'))==1
    for variant in variants:
        final=variant['final']; vid=variant['id']
        checks=final['check_ids']
        for cid in checks:
            review=s.quality._get(cid); assert review['verdict']=='pass',review
        delivery={'folder_id':'folder','reviewer':'fixture-operator','account':'offline-drive',
                  'valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                  'artifact_id':final['artifact_id'],'target_hash':final['sha256'],'check_ids':checks}
        r=act('post',f'/api/variants/{vid}/deliver',delivery,rev=1)
        assert r.status_code==400 and r.json()['error']=='acceptance_blocked',r.text
        r=act('post',f'/api/variants/{vid}/reviews',{'check_type':'creative','verdict':'pass','target_hash':final['sha256'],'reviewer':'fixture-operator'})
        assert r.status_code==201,r.text
        delivery['check_ids']=checks+[r.json()['review']['id']]
        r=act('post',f'/api/variants/{vid}/deliver',delivery,rev=1); assert r.status_code==202,r.text
        out=w.tick(); assert out['status']=='verified',out
        assert out['cleanup']['state']=='verified'
        again=act('post',f'/api/variants/{vid}/deliver',delivery,rev=1)
        assert again.json()['delivery']['status']=='verified',again.text
    assert len(s.delivery.drive.list_files('folder'))==4
    assert s.db.conn.execute('SELECT count(*) FROM attempts').fetchone()[0]==4


def test_action_atomic_rollback(application):
    from modules.factory.api.idempotency import IdempotencyStore
    s,*_=application
    store=IdempotencyStore(s.db)
    def fail():
        s.commands.enqueue('analyze',{'seed_id':'x'})
        raise RuntimeError('simulated process interruption before response')
    with pytest.raises(RuntimeError): store.run_local('atomic','POST','/action',{},fail)
    assert s.db.conn.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
    assert not s.db.uow().records.get('api_request','atomic')


def test_authoritative_revision_and_no_generic_drafts(application):
    s,c,act,w,root=application; body,art=prepare(application)
    r=act('patch','/api/experiments/fixture-exp/draft',{'reason':'change'},rev=0)
    assert r.status_code==409
    assert s.db.conn.execute("SELECT count(*) FROM records WHERE kind='experiment_draft'").fetchone()[0]==0


def test_backup_contains_durable_receipts_and_restores_blocked(application,tmp_path):
    from modules.factory.operations.backup_restore import create_backup,restore_into
    from modules.factory.store import Database
    s,c,act,w,root=application
    receipts=root/'data/factory/providers';receipts.mkdir()
    (receipts/'accepted.json').write_text(json.dumps({'submission_id':'durable-original','status':'unknown'}))
    backup=tmp_path/'backup';create_backup(s.db,root,backup)
    fresh=tmp_path/'fresh';restore_into(backup,fresh)
    assert json.loads((fresh/'data/factory/providers/accepted.json').read_text())['submission_id']=='durable-original'
    db=Database(fresh/'data/factory/factory.db')
    assert db.conn.execute("SELECT 1 FROM meta WHERE key='restore_pending'").fetchone()
    db.close()


def test_owned_tool_survives_real_caller_process_loss(application):
    import os,subprocess,sys,time
    s,c,act,w,root=application
    marker=root/'tool-complete'
    argv=[sys.executable,'-c',"import pathlib,time; time.sleep(1); pathlib.Path(__import__('sys').argv[1]).write_text('done')",str(marker)]
    code="from modules.factory.store import Database; from modules.factory.resources.runner import OwnedRunner; import json,sys; db=Database(sys.argv[1]); OwnedRunner(db,sys.argv[2],'interrupted-video')(json.loads(sys.argv[3]),timeout=10)"
    process=subprocess.Popen([sys.executable,'-c',code,s.db.path,str(root/'processes'),json.dumps(argv)])
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        records=s.db.conn.execute("SELECT body FROM records WHERE kind='resource' AND json_extract(body,'$.owner')='interrupted-video'").fetchall()
        if records:break
        time.sleep(.05)
    assert records
    process.kill();process.wait(timeout=5)
    from modules.factory.resources.runner import OwnedRunner
    result=OwnedRunner(s.db,root/'processes','interrupted-video')(argv,timeout=10)
    assert result.returncode==0 and marker.read_text()=='done'
    assert len(list((root/'processes').glob('*.json')))==1
    assert s.cleanup.cleanup('interrupted-video')['state']=='verified'


def test_public_commands_reject_malformed_payloads(application):
    s,c,act,w,root=application
    for path,body in [('/api/seeds',{}),('/api/seeds',[]),('/api/experiments',{'blueprint_id':42}),('/api/variants/x/reviews',{})]:
        r=act('post',path,body)
        assert r.status_code==400 and r.json()['error']=='invalid_command',r.text
    assert c.get('/api/events?after=invalid').status_code==400


def test_local_render_capacity_survives_expired_worker(application):
    from modules.factory.domain.records import Job
    s,c,act,w,root=application
    s.scheduler.submit_plan([Job(schema_version='job.v1',id=x,logical_key=x,phase='render') for x in ['r1','r2']])
    first=s.scheduler.claim();assert first['id']=='r1'
    with s.db.uow() as u:
        u.conn.execute("INSERT INTO meta(key,value) VALUES('local_work:r1','{}')")
        u.conn.execute("UPDATE jobs SET lease_expires='2000-01-01' WHERE id='r1'")
        u.conn.execute("UPDATE capacity_holds SET expires_at='2000-01-01' WHERE job_id='r1'")
    s.scheduler.reclaim_expired()
    assert s.scheduler.status_snapshot()['capacities']['local_render']['used']==1
    assert s.scheduler.claim()['id']=='r1' # recovery, not a second render
    assert s.scheduler.claim() is None


def test_redaction_does_not_mistake_content_path_for_oauth():
    from modules.factory.events.redact import redact
    assert redact('/tmp/data/1234/abcdef0123456789/media.mp4')=='/tmp/data/1234/abcdef0123456789/media.mp4'
    assert redact('4/'+'A'*70) != '4/'+'A'*70


def test_caption_clock_accepts_fractional_frame_rate():
    from modules.factory.rendering.ffmpeg_fast import captions_ass
    text=captions_ass([{'start_frame':30,'end_frame':60,'text':'Visible words'}],30.0)
    assert 'Dialogue: 0,0:00:01.00,0:00:02.00,' in text
