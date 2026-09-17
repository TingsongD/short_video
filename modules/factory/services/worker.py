"""Independent durable application worker. Closing the browser cannot cancel it."""
import json
import time
from pathlib import Path
from ..domain.errors import ContractError
from ..domain.records import content_hash
from ..execution.effects import EffectService
from ..store.uow import utcnow
from ..testing.fakes import ProviderError


class ApplicationWorker:
    def __init__(self, services):
        self.s = services
        self.scheduler = services.scheduler

    def tick(self):
        with self.s.db.uow() as u:
            u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('worker_heartbeat',?)",(json.dumps({'at':utcnow(),'worker':self.scheduler.worker_id}),))
        self.scheduler.reclaim_expired()
        job = self.scheduler.claim('collect') or self.scheduler.claim('observe') or self.scheduler.claim()
        if not job: return None
        try:
            with self.scheduler.heartbeat(job['id'],job['fencing_token']):
                row=self.s.db.uow().records.get('appcommand',job['id'])
                if row:
                    command=json.loads(row['body'])
                    result=self.execute(command['kind'],command['input'],job)
                else:
                    result=self.production(job)
            if result.get('status')=='awaiting_review':
                self.scheduler.transition(job['id'],job['fencing_token'],'awaiting_review')
                with self.s.db.uow() as u:
                    u.conn.execute('DELETE FROM capacity_holds WHERE job_id=?',(job['id'],))
            elif result.get('status') in ('running','observer_lost','pending','unknown'):
                self.scheduler.defer(job['id'],job['fencing_token'],result['status'])
            else:
                self.s.commands.finish(job['id'],result)
                self.scheduler.complete(job['id'],job['fencing_token'])
            return {'job_id':job['id'], **result}
        except ContractError as error:
            if error.code in ('remote_unfinished','capacity_full','retry_backoff'):
                self.scheduler.defer(job['id'],job['fencing_token'],error.code)
            else:
                self.scheduler.fail(job['id'],job['fencing_token'],error.code)
            with self.s.db.uow() as u:
                u.events.append('factory','command_blocked',{'job_id':job['id'],'error':error.code,'detail':error.detail})
            return {'job_id':job['id'],'status':'blocked','error':error.code,'detail':error.detail}
        except ProviderError as error:
            # Only observation/transfer failures may repeat. A submit timeout
            # remains an unresolved attempt and is reconciled by its identity.
            retryable=error.transient and error.code in ('download_transport_failed','poll_failed')
            self.scheduler.fail(job['id'],job['fencing_token'],error.code,retryable=retryable)
            return {'job_id':job['id'],'status':'retry' if retryable and job['retry_count']<5 else 'failed','error':error.code}
        except Exception as error:
            self.scheduler.fail(job['id'],job['fencing_token'],'handler_error:'+type(error).__name__)
            with self.s.db.uow() as u:
                u.events.append('factory','command_failed',{'job_id':job['id'],'error':type(error).__name__})
            # Keep a safe typed failure; tests may enable raising for diagnostics.
            if self.s.config.get('raise_worker_errors'): raise
            return {'job_id':job['id'],'status':'failed','error':type(error).__name__}

    def execute(self,kind,body,job):
        s=self.s
        if kind in ('retry_local','release_local'):
            from .recovery import retry_local,release_local
            return (retry_local if kind=='retry_local' else release_local)(s,body['job_id'],body['reviewer'])
        if kind=='analysis_collect':return s.analysis_work.collect(body)
        if kind=='speech_fit':return s.audio_work.fit(body)
        if kind=='publish':return s.publication_work.execute(body,job)
        if kind=='publication_observe':return {'publication':s.publishing.reconcile(body['publication_id'])}
        if kind=='readback':return {'snapshot':s.require('readback').collect(body['publication_id'],body['horizon']).to_dict()}
        if kind=='decision':return {'decision':s.learning.decide(body['experiment_id'],body['revision'])}
        if kind=='effect':return s.effect_work.execute(body,job)
        if kind=='research_evaluate':
            from ..discovery.service import DiscoveryService
            pool=[];histories={}
            for pid in body['plan_ids']:
                plan=s.effect_work.get(pid)
                if plan['kind']!='research':raise ContractError('invalid_research_plan','plan_id')
                for operation in plan['operations']:
                    saved=s.commands.get(pid+':'+operation['key'])
                    if saved['status']!='succeeded':raise ContractError('research_unfinished','job')
                    posts=saved['command']['result']['result'].get('posts',[])
                    if operation['request']['kind']=='creator_history':
                        for post in posts:histories.setdefault((post.get('platform'),post.get('creator_id')),[]).append(post)
                    else:pool.extend(posts)
            for p in pool:histories.setdefault((p.get('platform'),p.get('creator_id')),[])
            policy=body.get('policy',{})
            svc=DiscoveryService(s.db,s.seeds,s.executor,None)
            result=svc._finish(body['run_id'],[],0,0,policy.get('mode','either'),policy.get('baseline_threshold',5),policy.get('follower_threshold',2),[],[],{},pool,None,True,history_by_creator=histories)
            return {'status':'complete','discovery':result.to_dict()}
        if kind=='analyze':
            return {'blueprint':s.analysis.import_observations(body['seed_id'],body['observations'],body['reviewer']).to_dict()}
        if kind=='quote':
            exp=s._current(body['experiment_id'],body['revision']); fps=exp.output_clock['num']/exp.output_clock['den']
            takes=[]
            for key in 'ABCD':
                for seg in s.experiments._variant(exp.experiment_id,key).segments:
                    picture=seg.get('picture') or {}; req=dict(picture.get('request') or {})
                    if picture.get('artifact_id'):
                        art=s.db.uow().artifacts.get(picture['artifact_id'])
                        req.update(artifact_id=picture['artifact_id'],sha256=art['sha256'],source_in_s=picture.get('source_in_s',0))
                    elif not req:
                        raise ContractError('missing_picture','segment',seg['id'])
                    takes.append({'variant':key,'slot':seg['id'],'duration_s':(seg['target']['end_frame']-seg['target']['start_frame'])/fps,
                                  'handle_s':picture.get('handle_s',0),'request':req})
            provider='google_vertex' if exp.provider_policy.choice=='vertex' else 'jimeng_canvas'
            allowed=exp.provider_policy.allowed_models.get(provider,[])
            pinned={t['request'].get('model') for t in takes if t['request'].get('model')}
            if len(pinned)>1 or pinned and not pinned.issubset(set(allowed)):
                raise ContractError('pinned_route_mismatch','model')
            model=next(iter(pinned),allowed[0] if len(allowed)==1 else '')
            imported=all(t['request'].get('artifact_id') for t in takes)
            adapter=s.providers.get(provider)
            if not imported and (adapter is None or not model):
                raise ContractError('generation_route_unavailable','provider/model','Import footage or configure a qualified route and model')
            if imported:
                durations=[max(t['duration_s']+t.get('handle_s',0) for t in takes)]
            else:
                durations=adapter.capabilities(model).get('durations_s',[])
                if not durations: raise ContractError('model_catalog_unavailable','model',model)
            s.production.adapter=adapter
            pid='plan-'+content_hash([exp.experiment_id,exp.revision,exp.content_hash])[:24]
            old=s.production._plan(pid)
            if old: return s.production.status(pid)
            return s.production.plan(pid,exp.experiment_id,exp.revision,takes,provider,model,durations,now=utcnow())
        if kind=='run':
            return {'jobs':s.production.submit(body['plan_id']),'plan_id':body['plan_id']}
        if kind=='reconcile':
            rows=s.db.conn.execute('SELECT id FROM attempts WHERE job_id=?',(body['job_id'],)).fetchall()
            if not rows: raise ContractError('no_remote_attempt','job_id')
            results=[]
            for r in rows:
                spec=s.executor._intent_body(r['id']);adapter=s.providers.get(spec.get('provider'))
                if adapter is None:raise ContractError('reconcile_route_unavailable','provider')
                s.executor.provider=adapter;results.append(s.executor.reconcile(r['id']))
            return {'attempts':results}
        if kind=='studio_open':
            variant,final,path,binding=s._final(body['variant_id'])
            if binding!=body['binding']:raise ContractError('stale_revision','studio')
            workspace=s.composition.root/binding['composition_id']/f"r{binding['composition_revision']}"
            return s.studio.open_session(body['session_id'],str(workspace),variant['id'])
        if kind=='studio_close':
            return s.studio.close_session(body['session_id'])
        if kind=='cleanup':
            receipt=s.delivery._get(body['delivery_id'])
            if not receipt or receipt['status']!='verified':raise ContractError('delivery_not_verified','delivery')
            result=s.cleanup.cleanup(body['variant_id'])
            s.delivery._set(body['delivery_id'],cleanup_receipt=json.dumps(result))
            if result['state']!='verified':raise ContractError('cleanup_incomplete','resources')
            v=s.detail('variantplan',body['variant_id']);plan=s.plan_for(v['experiment_id'])
            with s.db.uow() as u:
                u.conn.execute("UPDATE jobs SET status='succeeded',lease_owner=NULL,lease_expires=NULL WHERE id=? AND status='awaiting_review'",(plan['id']+':del:'+v['variant_key'],))
                u.events.append('factory','video_completed',{'variant_id':v['id'],'delivery_id':body['delivery_id'],'link':receipt['drive_link']})
            return {'status':'verified','cleanup':result,'link':receipt['drive_link']}
        if kind=='delivery':
            v,final,path,binding=s._final(body['variant_id'])
            if binding != body['binding']: raise ContractError('stale_revision','delivery')
            s.quality.accept(path,body['check_ids'],binding)
            effects=EffectService(s.db,s.executor)
            def scope(request,*unused):
                att=effects.prepare(body['authorization_id'],'delivery',job['id'],job['fencing_token'],self.scheduler.worker_id)
                s.executor.require_request(att,request)
                return att
            s.delivery.effects=scope
            result=s.delivery.deliver(body['delivery_id'],path,body['name'],body['folder_id'],
                      variant_plan_id=v['id'],experiment_revision=v['experiment_revision'])
            if result['status']!='verified': return result
            cleanup=s.cleanup.cleanup(v['id'])
            s.delivery._set(body['delivery_id'],cleanup_receipt=json.dumps(cleanup))
            if cleanup['state']!='verified': raise ContractError('cleanup_incomplete','resources',json.dumps(cleanup))
            with s.db.uow() as u:
                plan=s.plan_for(v['experiment_id'])
                u.conn.execute("UPDATE jobs SET status='succeeded',lease_owner=NULL,lease_expires=NULL,updated_at=? WHERE id=? AND status='awaiting_review'",(utcnow(),plan['id']+':del:'+v['variant_key']))
                u.events.append('factory','video_completed',{'variant_id':v['id'],'delivery_id':body['delivery_id'],'link':result['link']})
            return {**result,'cleanup':cleanup}
        raise ContractError('handler_unavailable','command',kind)

    def production(self,job):
        s=self.s
        row=s.db.uow().records.get('workitem',job['id'])
        if not row: raise ContractError('handler_unavailable','job',job['id'])
        node=json.loads(row['body']); plan=s.production._plan(node['plan_id'])
        s._current(plan['experiment_id'],plan['experiment_revision'])
        if node['kind'] in ('picture','download','review'):
            s.production.adapter=s.providers.get(node['provider'])
            s.executor.provider=s.production.adapter
            s.production.selector=lambda n:self.asset_verdict(plan,n)
            outcome=s.production._execute(plan['id'],node,job)
            return {'status':outcome,'node':node['node_key']}
        if node['kind']=='compose':
            # Persist before starting any process. An expired worker lease is
            # not evidence that its renderer stopped. Only this job recovers it.
            with s.db.uow() as u:
                u.conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',('local_work:'+job['id'],json.dumps({'plan':plan['id'],'variant':node['consumers'][0]})))
            result=self.render(plan,node['consumers'][0])
            if result.get('status')=='rendered':
                with s.db.uow() as u:
                    u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+job['id'],))
            return result
        if node['kind']=='deliver':
            return {'status':'awaiting_review','action':'Review the final and authorize its registered delivery'}
        raise ContractError('handler_unavailable','kind',node['kind'])

    def asset_verdict(self,plan,node):
        ids=node.get('artifact_ids') or []
        if not ids:
            ids=next((n['artifact_ids'] for n in self.s.production._nodes(plan['id']).values() if n['kind']=='download' and node['node_key'] in n['depends']),[])
        if not ids: return 'uncertain'
        for aid in ids:
            art=self.s.db.uow().artifacts.get(aid)
            rows=self.s.db.conn.execute("SELECT body FROM records WHERE kind='review' AND json_extract(body,'$.check_type')='asset' AND json_extract(body,'$.binding.plan_hash')=? AND json_extract(body,'$.binding.artifact_id')=? ORDER BY created_at DESC",(plan['plan_hash'],aid)).fetchall()
            if not rows: return 'uncertain'
            review=json.loads(rows[0][0])
            if review['target_hash']!=art['sha256'] or not review.get('reviewer'): return 'uncertain'
            if review['verdict']!='pass': return 'reject' if review['verdict']=='fail' else 'uncertain'
        return 'accept'

    def render(self,plan,key):
        s=self.s; exp=s._current(plan['experiment_id'],plan['experiment_revision']); variant=s.experiments._variant(exp.experiment_id,key)
        from ..resources.runner import OwnedRunner
        s.rendering.fast.runner=OwnedRunner(s.db,Path(s.db.path).parent/'processes',variant.id)
        fps=exp.output_clock['num']/exp.output_clock['den']; segments=[]; captions=[]; pictures=[]; audio=[]; narration=[]
        nodes=s.production._nodes(plan['id'])
        for seg in variant.segments:
            pic=seg['picture']; target=seg['target']; start,end=target['start_frame'],target['end_frame']
            node=next(n for n in nodes.values() if n['kind']=='picture' and any(t['slot']==seg['id'] and t['variant']==key for t in n['takes']))
            dl=next(n for n in nodes.values() if n['kind']=='download' and node['node_key'] in n['depends'])
            aids=dl['artifact_ids']; offset=start
            for i,aid in enumerate(aids):
                art=s.db.uow().artifacts.get(aid); path=s.artifacts.verified_path(aid)
                frames=end-start if len(aids)==1 else min(end-offset,round(node['allocations'][i]['covers_s']*fps))
                if frames<=0: break
                inp=pic.get('source_in_s',0) if len(aids)==1 else 0
                item={'id':seg['id']+f'-{i}','kind':'picture','artifact_id':aid,'sha256':art['sha256'],
                      'in_frame':offset,'out_frame':offset+frames,'source_in_s':inp,'source_out_s':inp+frames/fps,
                      'effects':seg.get('effects',[]),'transition_out':seg.get('transition','cut'),
                      'transition_frames':seg.get('transition_frames',0)}
                if i==len(aids)-1 and item['transition_out']=='crossfade':
                    item['source_out_s']+=item['transition_frames']/fps
                segments.append(item); pictures.append({**item,'src':str(path),'frames':frames,'media_kind':art['kind']});offset+=frames
            if offset!=end: raise ContractError('picture_coverage_incomplete','segment',seg['id'])
            for c in seg.get('captions') or []:
                captions.append({'id':seg['id']+'-caption-'+str(len(captions)),**c})
            speech=seg.get('speech') or {}
            if speech.get('artifact_id'):
                aid=speech['artifact_id']; art=s.db.uow().artifacts.get(aid); path=s.artifacts.verified_path(aid)
                item={'id':seg['id']+'-speech','kind':'audio','artifact_id':aid,'sha256':art['sha256'],'in_frame':start,'out_frame':end,
                      'source_in_s':0,'source_out_s':(end-start)/fps,'gain':speech.get('gain',1)}
                segments.append(item); audio.append({**item,'src':str(path)}); narration.append({'path':str(path),'sha256':art['sha256'],'start_frame':start,'end_frame':end})
            elif seg.get('copy'):
                raise ContractError('speech_required','segment',seg['id'])
        music=exp.music
        if music.get('artifact_id'):
            aid=music['artifact_id']; art=s.db.uow().artifacts.get(aid); path=s.artifacts.verified_path(aid)
            item={'id':'music','kind':'audio','artifact_id':aid,'sha256':art['sha256'],'in_frame':0,'out_frame':variant.target_frames,
                  'source_in_s':music.get('source_in_s',0),'source_out_s':music.get('source_in_s',0)+variant.target_frames/fps,'gain':music.get('gain',.1)}
            segments.append(item); audio.append({**item,'src':str(path)})
        if not audio: raise ContractError('audio_required','experiment','Import or synthesize the reviewed audio')
        source_art=s.db.uow().artifacts.get(pictures[0]['artifact_id']); probe=json.loads(source_art['probe'])
        video=next(x for x in probe['streams'] if x['codec_type']=='video')
        clock={'fps':fps,'width':video['width'],'height':video['height'],'total_frames':variant.target_frames}
        renderer='hypit' if any(x.get('transition_out') not in ('cut','none','') or 'kenburns' in x.get('effects',[]) for x in pictures) else 'ffmpeg_fast'
        cid='comp-'+content_hash([plan['id'],key])[:24]
        result=s.composition.compile(cid,exp.experiment_id,key,plan['id'],segments,captions,clock,renderer,plan_hash=plan['plan_hash'],now=utcnow())
        if result['diagnostics']: raise ContractError('compile_failed','diagnostics',json.dumps(result['diagnostics']))
        comp=result['composition']; bid='build-'+content_hash([cid,comp['content_hash']])[:24]
        if not s.db.uow().records.get('renderbuild',bid): s.rendering.register(bid,comp,now=utcnow())
        build=s.rendering._build(bid)
        if build['status'] not in ('collected','succeeded'):
            svrun=s.composition.root/cid/f"r{comp['revision']}"/'render.svrun'
            if renderer=='hypit':
                from ..studio.launcher import prepare_local,capture_owned
                prepare_local(svrun.parent,s.rendering.fast.runner)
            result=s.rendering.dispatch(bid,pictures,captions,audio,clock,svrun_path=svrun)
            if renderer=='hypit': capture_owned(s.resources,variant.id,svrun.parent)
            if result['status']=='running': result=s.rendering.observe(bid)
            if result['status'] not in ('succeeded','collected'): return result
        build=s.rendering._build(bid)
        final={'artifact_id':build['output_artifact_id'],'sha256':build['output_sha256']} if build['status']=='collected' else s.rendering.collect(bid,now=utcnow())
        final.update(composition_id=cid,build_id=bid)
        path=s.artifacts.verified_path(final['artifact_id']); binding=s.quality.binding(path,cid,final['artifact_id'])
        expected={**clock,'frames':variant.target_frames,'has_audio':True,'narration':narration,'narration_required':any(seg.get('copy') for seg in variant.segments)}
        tech='technical-'+bid
        if not s.quality._get(tech): s.quality.inspect(tech,path,expected,binding=binding)
        checks=[tech]
        if key!='A':
            _,a,apath,_=s._final(exp.experiment_id+':a'); regions=[]; cursor=0
            for region in sorted(variant.allowed_regions,key=lambda r:r.start):
                if region.start>cursor: regions.append({'start_frame':cursor,'end_frame':region.start})
                cursor=max(cursor,region.end)
            if cursor<variant.target_frames: regions.append({'start_frame':cursor,'end_frame':variant.target_frames})
            check='regions-'+bid
            if not s.quality._get(check): s.quality.check_regions(check,apath,path,regions,fps,binding=binding)
            checks.append(check)
        final.update(check_ids=checks,binding=binding)
        with s.db.uow() as u:
            u.conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',('final:'+variant.id,json.dumps(final)))
        return {'status':'rendered','variant_id':variant.id,'final':final,'review_required':True}

    def run(self,once=False):
        while True:
            result=self.tick()
            if once: return result
            if result is None: time.sleep(.25)
