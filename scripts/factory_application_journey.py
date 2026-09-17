"""Exercise the actual loopback app and its independent worker, offline only.

Fixture operator reviews are explicitly labeled; they never qualify live media.
The HTTP application creates every final, review and delivery receipt.
"""
import argparse
import copy
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from modules.factory.audio import pcm
from modules.factory.testing.fixtures import _moving_mp4


def journey(url,root,frames=900,deliver=True):
    if not url.startswith('http://127.0.0.1:'):raise ValueError('isolated loopback fixture app required')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    client=httpx.Client(base_url=url,timeout=120)
    assert client.get('/api/health').json()['mode']=='offline'
    token=client.post('/api/session').json()['session_token'];seq=0
    eid='fixture-'+uuid.uuid4().hex[:10]; evidence={'experiment_id':eid,'frames':frames,'stages':[]}
    def stage(name,**data):
        evidence['stages'].append({'stage':name,'at':datetime.now(timezone.utc).isoformat(),**data})
        (root/'journey.json').write_text(json.dumps(evidence,indent=2))
    def act(path,body=None,rev=None,data=None,name=None):
        nonlocal seq
        seq+=1;headers={'x-csrf-token':token,'idempotency-key':eid+'-'+str(seq)}
        if rev:headers['x-expected-revision']=str(rev)
        if name:headers['x-filename']=name
        response=client.post(path,json=body if data is None else None,content=data,headers=headers)
        assert response.is_success,(response.status_code,response.text)
        return response.json()
    def await_job(jid,timeout=240):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            job=client.get('/api/jobs/'+jid).json()
            if job['status']=='succeeded':return job['command']['result']
            if job['status'] in ('failed','blocked'):raise RuntimeError(job)
            time.sleep(.2)
        raise TimeoutError(jid)
    seconds=frames/30;source=root/'source.mp4';_moving_mp4(source,seconds,size='180x320')
    seed=act('/api/seeds',{'url':'https://youtu.be/'+eid[-10:]+'x'})['seed']['seed']['id']
    art=act('/api/imports',data=source.read_bytes(),name='timing-reference.mp4')['artifact']['id']
    act(f'/api/seeds/{seed}/media',{'artifact_id':art})
    boundaries=[0,frames//3,2*(frames//3),frames]
    obs={'beats':[{'id':f'b{i}','role':['hook','body','cta'][i],'start_s':boundaries[i]/30,'end_s':boundaries[i+1]/30,'confidence':'reviewed','visual_event':'moving offline fixture'} for i in range(3)],'transcript':[{'id':'fixture-sound','start_s':0,'end_s':seconds,'text':'Instrumental fixture tone; no human speech'}],'music':{'role':'bed'}}
    analysis=act(f'/api/seeds/{seed}/analyze',{'observations':obs,'reviewer':'offline-fixture-operator'})
    bp=await_job(analysis['job_id'])['blueprint'];stage('analyzed')
    act(f"/api/blueprints/{bp['id']}/review",{'content_hash':bp['content_hash'],'reviewer':'offline-fixture-operator'})
    template=act('/api/templates',{'blueprint_id':bp['id'],'id':eid+'-template'})['template']['id']
    segments=[]
    for i in range(3):
        start,end=boundaries[i:i+2];wav=pcm.write_wav(pcm.sine((end-start)/30,amp=6500,freq=220+110*i))
        audio=act('/api/imports',data=wav,name=f'narration-fixture-{i}.wav')['artifact']['id']
        segments.append({'id':f's{i}','slot_id':f'slot-{i}','role':['hook','body','cta'][i],'target':{'start_frame':start,'end_frame':end},'picture':{'artifact_id':art,'source_in_s':start/30},'speech':{'artifact_id':audio},'copy':f'Offline narration fixture {i}','captions':[{'text':f'Control caption {i}','start_frame':start,'end_frame':end}],'transition':'cut','claims':[]})
    variants=[]
    for i,key in enumerate('BCD'):
        segs=copy.deepcopy(segments);segs[i]['captions'][0]['text']=f'Variation {key}'
        variants.append({'key':key,'factor':['hook','body','ending'][i],'regions':[segments[i]['target']],'segments':segs,'hypothesis':'Caption retention fixture','primary_metric':'retention','allowed_fields':['captions']})
    act('/api/experiments',{'id':eid,'blueprint_id':bp['id'],'template_id':template,'segments':segments,'variants':variants})
    quote=act(f'/api/experiments/{eid}/quote',{},1)['quote']
    plan=await_job(quote['job_id'])['plan'];stage('quoted',plan_hash=plan['plan_hash'])
    act(f'/api/experiments/{eid}/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'offline-fixture-operator'},1)
    act(f'/api/experiments/{eid}/assets/review',{'plan_hash':plan['plan_hash'],'reviewer':'offline-fixture-operator','artifact_ids':[art],'verdict':'pass'},1)
    run=act(f'/api/experiments/{eid}/run',{},1)['run'];await_job(run['job_id']);stage('queued')
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        result=client.get(f'/api/experiments/{eid}/results').json()
        if all(v.get('final') for v in result['variants']):break
        jobs=client.get('/api/collections/queue').json()['items']['jobs']
        failed=[j for j in jobs if j['experiment_id']==eid and j['status'] in ('failed','blocked')]
        if failed:raise RuntimeError(failed)
        time.sleep(.5)
    else:raise TimeoutError('four exports')
    assert len({v['final']['sha256'] for v in result['variants']})==4,'Treatment rendered identically to control'
    stage('four_exports',finals=[{'variant':v['variant_key'],**v['final']} for v in result['variants']])
    if deliver:
        receipts=[]
        for v in result['variants']:
            f=v['final'];r=act(f"/api/variants/{v['id']}/reviews",{'check_type':'creative','verdict':'pass','target_hash':f['sha256'],'reviewer':'offline-fixture-operator','notes':'Synthetic fixture only; not live creative acceptance'})['review']
            d=act(f"/api/variants/{v['id']}/deliver",{'folder_id':'fixture-folder','account':'offline-drive','reviewer':'offline-fixture-operator','valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'artifact_id':f['artifact_id'],'target_hash':f['sha256'],'check_ids':f['check_ids']+[r['id']]},1)['delivery']
            receipts.append(await_job(d['job_id']))
        stage('delivery_cleanup',receipts=receipts)
    return evidence

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:5197');p.add_argument('--root',required=True);p.add_argument('--frames',type=int,default=900);p.add_argument('--no-delivery',action='store_true');a=p.parse_args()
    evidence=journey(a.url,a.root,a.frames,not a.no_delivery)
    print(json.dumps({'experiment_id':evidence['experiment_id'],'frames':evidence['frames'],'stages':[s['stage'] for s in evidence['stages']]}))
