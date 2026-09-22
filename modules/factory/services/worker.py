"""Independent durable application worker. Closing the browser cannot cancel it."""
import json
import math
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from ..domain.errors import ContractError
from ..rendering.ffmpeg_fast import RenderTimeout
from ..domain.records import content_hash
from ..execution.effects import EffectService
from ..store.uow import utcnow
from ..testing.fakes import ProviderError
from ..diagnostics import event

# Result-state contract for tick(): a handler may only complete a job
# through an explicitly successful outcome — or by returning data with no
# status at all. Anything unrecognized is a failure, never a silent
# success.
DEFERRED = {'running', 'observer_lost', 'pending', 'unknown'}
SUCCEEDED = {'rendered', 'verified', 'complete', 'succeeded', 'downloaded',
             'submitted', 'reviewed', 'reused_validated_asset', 'manual',
             'collected', 'accepted', 'released', 'ok', 'done'}
FAILED = {'failed', 'conflict', 'unverified', 'cancelled',
          'no_remote_trace', 'error'}


class ApplicationWorker:
    def __init__(self, services):
        self.s = services
        self.scheduler = services.scheduler

    def tick(self):
        with self.s.db.uow() as u:
            u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('worker_heartbeat',?)",(json.dumps({'at':utcnow(),'worker':self.scheduler.worker_id,'pid':os.getpid(),'db':str(self.s.db.path),'version':self.WORKER_VERSION}),))
        self.scheduler.reclaim_expired()
        job = self.scheduler.claim('collect') or self.scheduler.claim('observe') or self.scheduler.claim()
        if not job: return None
        event("job_started", job_id=job['id'], stage=job['phase'])
        try:
            with self.scheduler.heartbeat(job['id'],job['fencing_token']):
                row=self.s.db.uow().records.get('appcommand',job['id'])
                if row:
                    command=json.loads(row['body'])
                    result=self.execute(command['kind'],command['input'],job)
                else:
                    result=self.production(job)
            outcome = result.get('status')
            if outcome == 'awaiting_review':
                self.scheduler.transition(job['id'],job['fencing_token'],'awaiting_review')
                with self.s.db.uow() as u:
                    u.conn.execute('DELETE FROM capacity_holds WHERE job_id=?',(job['id'],))
            elif outcome in DEFERRED:
                self.scheduler.defer(job['id'],job['fencing_token'],result.get('reason') or outcome,result.get('defer_s',2))
            elif outcome is None or outcome in SUCCEEDED:
                self.s.commands.finish(job['id'],result)
                self.scheduler.complete(job['id'],job['fencing_token'])
            else:
                reason = outcome if outcome in FAILED else 'unrecognized_result_state:'+str(outcome)
                self.scheduler.fail(job['id'],job['fencing_token'],reason)
                with self.s.db.uow() as u:
                    u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+job['id'],))
                    u.events.append('factory','command_failed',{'job_id':job['id'],'error':reason})
            event("job_result", job_id=job['id'], status=outcome or 'succeeded')
            return {'job_id':job['id'], **result}
        except ContractError as error:
            if error.code in ('remote_unfinished','capacity_full','retry_backoff'):
                delay = 2
                if error.code == 'retry_backoff':
                    from datetime import datetime
                    try:
                        delay = max(1, (datetime.fromisoformat(error.detail) - self.scheduler.clock()).total_seconds())
                    except (ValueError, TypeError):
                        pass
                self.scheduler.defer(job['id'],job['fencing_token'],error.code,delay)
                event('job_waiting', job_id=job['id'], code=error.code, status='pending')
                with self.s.db.uow() as u:
                    u.events.append('factory','command_waiting',{'job_id':job['id'],'reason':error.code})
                return {'job_id':job['id'],'status':'pending','reason':error.code}
            else:
                event("job_blocked", job_id=job['id'], code=error.code)
                self.scheduler.fail(job['id'],job['fencing_token'],error.code)
                with self.s.db.uow() as u:
                    u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+job['id'],))
            with self.s.db.uow() as u:
                u.events.append('factory','command_blocked',{'job_id':job['id'],'error':error.code,'detail':error.detail})
            return {'job_id':job['id'],'status':'blocked','error':error.code,'detail':error.detail}
        except ProviderError as error:
            event("provider_failed", job_id=job['id'], code=error.code)
            # Only observation/transfer failures may repeat. A submit timeout
            # remains an unresolved attempt and is reconciled by its identity.
            retryable=error.transient and error.code in ('download_transport_failed','poll_failed')
            self.scheduler.fail(job['id'],job['fencing_token'],error.code,retryable=retryable)
            with self.s.db.uow() as u:
                u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+job['id'],))
            return {'job_id':job['id'],'status':'retry' if retryable and job['retry_count']<5 else 'failed','error':error.code}
        except Exception as error:
            event("job_failed", job_id=job['id'], error_type=type(error).__name__)
            # Local, unpaid, re-entrant render work (compose nodes) that hit
            # a subprocess timeout is retried with the scheduler's bounded
            # backoff; every paid or ambiguous path stays terminal here.
            retryable=isinstance(error,(subprocess.TimeoutExpired,RenderTimeout)) and ':cmp:' in job['id']
            self.scheduler.fail(job['id'],job['fencing_token'],'handler_error:'+type(error).__name__,retryable=retryable)
            with self.s.db.uow() as u:
                u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+job['id'],))
                u.events.append('factory','command_retry' if retryable else 'command_failed',{'job_id':job['id'],'error':type(error).__name__})
            # Keep a safe typed failure; tests may enable raising for
            # diagnostics — but a scheduled retry is a handled outcome.
            if self.s.config.get('raise_worker_errors') and not retryable: raise
            return {'job_id':job['id'],'status':'retry' if retryable else 'failed','error':type(error).__name__}

    def execute(self,kind,body,job):
        s=self.s
        if kind in ('retry_local','release_local'):
            from .recovery import retry_local,release_local
            return (retry_local if kind=='retry_local' else release_local)(s,body['job_id'],body['reviewer'])
        if kind=='analysis_collect':return s.analysis_work.collect(body)
        if kind=='source_evidence':return s.source_work.execute(body,job)
        if kind=='speech_fit':return s.audio_work.fit(body)
        if kind=='publish':return s.publication_work.execute(body,job)
        if kind=='publication_observe':
            out=s.publishing.reconcile(body['publication_id'])
            pub=s.publishing.get(body['publication_id']) or {}
            if pub.get('status')=='scheduled':
                sched=pub.get('scheduled_at') or ''
                now_dt=self.scheduler.clock()
                try:
                    sched_dt=datetime.fromisoformat(
                        sched.replace('Z','+00:00')) if sched else None
                except ValueError:
                    sched_dt=None
                if sched_dt is not None and \
                        now_dt < sched_dt + timedelta(hours=24):
                    # Keep polling a remotely-scheduled post until it
                    # goes public (bounded to 24h past its instant) —
                    # a local 'scheduled' is not a terminal state.
                    delay=max(60.0,(sched_dt-now_dt).total_seconds()+60)
                    delay=min(delay,900.0)
                    return {'status':'pending','publication':out,
                            'defer_s':delay}
                with s.db.uow() as u:
                    u.events.append(
                        f"publication:{body['publication_id']}",
                        'observation_exhausted',{})
                return {'status':'complete','publication':out,
                        'observation':'exhausted'}
            return {'publication':out}
        if kind=='readback':
            chk=getattr(s,'checkpoints',None)
            if chk is not None:
                try:
                    snap=chk.collect(body['publication_id'],body['horizon'])
                except ContractError as error:
                    if error.code=='horizon_not_due':
                        delay=chk.seconds_until_due(
                            body['publication_id'], body['horizon'])
                        return {'status':'pending','error':'horizon_not_due',
                                'horizon':body.get('horizon'),
                                'defer_s':delay}
                    raise
                snap=snap.to_dict() if hasattr(snap,'to_dict') else snap
                if snap.get('completeness')=='complete':
                    self._after_readback(s,body)
                    return {'status':'complete','snapshot':snap}
                delay,st=chk.next_delay(body['publication_id'],
                                        body['horizon'])
                if st=='retrying' and delay is not None:
                    return {'status':'pending','snapshot':snap,
                            'defer_s':delay}
                return {'status':'failed','snapshot':snap}
            return {'snapshot':s.require('readback').collect(body['publication_id'],body['horizon']).to_dict()}
        if kind=='decision':return {'decision':s.learning.decide(body['experiment_id'],body['revision'],body.get('horizon',''),body.get('platform',''),account=body.get('account',''))}
        if kind=='select_seed':return {'selection':s.learning.select_seed(body['experiment_id'],body['revision'],body.get('horizon',''),account=body.get('account',''),accounts=body.get('accounts'))}
        if kind=='effect':return s.effect_work.execute(body,job)
        if kind=='auto_step':return s.autorun.step(body,job)
        if kind=='research_evaluate':
            from ..discovery.service import DiscoveryService
            pool=[];histories={};planned=[];received=[];per_query={};actual_calls=0;page_size=20
            for pid in body['plan_ids']:
                plan=s.effect_work.get(pid)
                if plan['kind']!='research':raise ContractError('invalid_research_plan','plan_id')
                for operation in plan['operations']:
                    saved=s.commands.get(pid+':'+operation['key'])
                    if saved['status']!='succeeded':raise ContractError('research_unfinished','job')
                    res=saved['command']['result'];posts=res['result'].get('posts',[])
                    req=operation['request'];label=req.get('query') or req.get('handle','')
                    page_size=req.get('page_size',page_size)
                    planned.append((label,req.get('page',1)))
                    per_query.setdefault(label,[]).append(req.get('page',1))
                    if posts:received.append((label,req.get('page',1)))
                    # Coverage is the count of real provider calls — a
                    # cache-hit operation made none.
                    if not res.get('cache_hit'):actual_calls+=1
                    if req['kind']=='creator_history':
                        for post in posts:histories.setdefault((post.get('platform'),post.get('creator_id')),[]).append(post)
                    else:pool.extend(posts)
            for p in pool:histories.setdefault((p.get('platform'),p.get('creator_id')),[])
            policy=body.get('policy',{})
            svc=DiscoveryService(s.db,s.seeds,s.executor,None)
            svc._calls=actual_calls
            queries=sorted(per_query)
            result=svc._finish(body['run_id'],queries,max((len(v) for v in per_query.values()),default=1),page_size,policy.get('mode','either'),policy.get('baseline_threshold',5),policy.get('follower_threshold',2),planned,received,per_query,pool,None,True,history_by_creator=histories)
            return {'status':'complete','discovery':result.to_dict()}
        if kind=='analyze':
            return {'blueprint':s.analysis.import_observations(body['seed_id'],body['observations'],body['reviewer']).to_dict()}
        if kind=='analysis_evidence':
            binding = {'expected_binding': body, 'job_id': job['id']} if body.get('edit_token') else {}
            return {'analysis':s.ref_analysis.run_machine_stages(body['seed_id'], **binding).to_dict()}
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
                    if exp.packaging.get('workflow', {}).get('reference_policy') == 'first_clip.v1':
                        from ..creative.references import bound_request
                        req = bound_request(s, exp, key, seg, req, body.get('reference_bindings') or {})
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
            output_binding=None
            if exp.packaging.get('flashcut_policy'):
                from .editorial_work import output_binding as editorial_binding
                output_binding=editorial_binding(s,exp)
            pid='plan-'+content_hash([exp.experiment_id,exp.revision,exp.content_hash,
                body.get('reference_bindings')])[:24] if body.get('reference_bindings') else 'plan-'+content_hash([exp.experiment_id,exp.revision,exp.content_hash])[:24]
            if output_binding:pid='plan-'+content_hash([pid,output_binding])[:24]
            old=s.production._plan(pid)
            if old: return s.production.status(pid)
            return s.production.plan(pid,exp.experiment_id,exp.revision,takes,provider,model,durations,now=utcnow(),output_binding=output_binding)
        if kind=='run':
            s.verify_run_gate(body['plan_id'])
            return {'jobs':s.production.submit(body['plan_id']),'plan_id':body['plan_id']}
        if kind=='reconcile':
            rows=s.db.conn.execute('SELECT id FROM attempts WHERE job_id=?',(body['job_id'],)).fetchall()
            if not rows: raise ContractError('no_remote_attempt','job_id')
            results=[]
            for r in rows:
                spec=s.executor._intent_body(r['id']);adapter=s.providers.get(spec.get('provider'))
                if adapter is None:raise ContractError('reconcile_route_unavailable','provider')
                s.executor.provider=adapter;results.append(s.executor.reconcile(r['id']))
            # Remote truth decides: an alive/finished effect resumes the
            # ORIGINAL job (its own poll/download path collects and
            # unblocks descendants — no resubmission, no new reservation).
            # All-unknown stays failed for evidence-based operator
            # resolution; a failed/cancelled attempt keeps the job dead.
            statuses={a['status'] for a in s.db.conn.execute(
                'SELECT status FROM attempts WHERE job_id=?',(body['job_id'],)).fetchall()}
            job=s.db.uow().jobs.get(body['job_id'])
            resumed=False
            if job and job['status'] in ('failed','blocked') and \
                    statuses & {'accepted','running','succeeded','downloaded'} and \
                    not statuses & {'failed','cancelled'}:
                from .recovery import unblock_descendants
                with s.db.uow() as u:
                    u.conn.execute("UPDATE jobs SET status='waiting_dependencies',lease_owner=NULL,"
                        "lease_expires=NULL,next_attempt_at=NULL,blocked_reason=NULL WHERE id=?",(body['job_id'],))
                    unblock_descendants(u,body['job_id'])
                    u.events.append('factory','job_resumed_by_reconcile',
                                    {'job_id':body['job_id'],'attempts':sorted(statuses)})
                resumed=True
            return {'attempts':results,'resumed':resumed}
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
        if kind=='delivery_reconcile':
            v,final,path,binding=s._final(body['variant_id'])
            exp=s._current(v['experiment_id'],v['experiment_revision'])
            if binding != body['binding']: raise ContractError('stale_revision','delivery')
            if exp.packaging.get('delivery_tracking') != 'verified_receipts.v1':
                raise ContractError('historical_delivery_unchanged','variant_id')
            account=getattr(s.delivery.drive,'expected_account','') or ('fixture-drive' if s.config.get('mode','offline')=='offline' else '')
            if body['folder_id'] != s.config.get('drive_folder_id') or body['account'] != account:
                raise ContractError('destination_not_authorized','folder_id/account')
            s.external_delivery_acceptance(v,final,path,binding)
            result=s.delivery.reconcile_external(body['delivery_id'],path,body['name'],body['folder_id'],body['file_id'],
                variant_plan_id=v['id'],experiment_revision=v['experiment_revision'],
                queue_job_id=final['plan_id']+':del:'+v['variant_key'])
            if result['status']!='verified':return result
            return self._finish_delivery(v,body['delivery_id'],result)
        if kind=='delivery':
            v,final,path,binding=s._final(body['variant_id'])
            if binding != body['binding']: raise ContractError('stale_revision','delivery')
            s.delivery_acceptance(v,final,path,binding,body['check_ids'])
            effects=EffectService(s.db,s.executor)
            def scope(request,*unused):
                att=effects.prepare(body['authorization_id'],'delivery',job['id'],job['fencing_token'],self.scheduler.worker_id)
                s.executor.require_request(att,request)
                return att
            s.delivery.effects=scope
            result=s.delivery.deliver(body['delivery_id'],path,body['name'],body['folder_id'],
                      variant_plan_id=v['id'],experiment_revision=v['experiment_revision'],
                      queue_job_id=(final['plan_id']+':del:'+v['variant_key']) if s._current(v['experiment_id']).packaging.get('delivery_tracking') == 'verified_receipts.v1' else '')
            if result['status']!='verified': return result
            return self._finish_delivery(v,body['delivery_id'],result)
        if kind=='delivery_retry':
            v,final,path,binding=s._final(body['variant_id'])
            original=s.commands.get(body['delivery_id'])['command']
            if not original or original['kind']!='delivery':raise ContractError('unknown_delivery','delivery_id')
            if binding != original['input']['binding']:
                raise ContractError('stale_revision','delivery')
            s.delivery_acceptance(v,final,path,binding,original['input']['check_ids'])
            effects=EffectService(s.db,s.executor)
            def retry_scope(request,*unused):
                att=effects.prepare(original['input']['authorization_id'],'delivery',job['id'],job['fencing_token'],self.scheduler.worker_id)
                s.executor.require_request(att,request)
                return att
            s.delivery.effects=retry_scope
            result=s.delivery.retry(body['delivery_id'],path)
            if result['status']!='verified': return result
            return self._finish_delivery(v,body['delivery_id'],result)
        raise ContractError('handler_unavailable','command',kind)

    def _finish_delivery(self,v,delivery_id,result):
        s=self.s
        cleanup=s.cleanup.cleanup(v['id'])
        s.delivery._set(delivery_id,cleanup_receipt=json.dumps(cleanup))
        if cleanup['state']!='verified': raise ContractError('cleanup_incomplete','resources',json.dumps(cleanup))
        with s.db.uow() as u:
            plan=s.plan_for(v['experiment_id'])
            u.conn.execute("UPDATE jobs SET status='succeeded',lease_owner=NULL,lease_expires=NULL,updated_at=? WHERE id=? AND status='awaiting_review'",(utcnow(),plan['id']+':del:'+v['variant_key']))
            u.events.append('factory','video_completed',{'variant_id':v['id'],'delivery_id':delivery_id,'link':result['link']})
        return {**result,'cleanup':cleanup}

    def _after_readback(self,s,body):
        """A completed checkpoint feeds the frozen-policy decision
        automatically when its horizon is the policy's horizon — the
        decision job is durable and idempotent by identity."""
        pub = (s.publishing.get(body['publication_id'])
               if getattr(s, 'publishing', None) else None) or {}
        exp = pub.get('experiment_id')
        rev = pub.get('experiment_revision')
        if not exp or not rev:
            return
        try:
            pol = s.learning.policy(exp, rev)
        except Exception:
            pol = None
        if not pol or pol.get('horizon') != body.get('horizon'):
            return
        platform = pub.get('platform', '')
        account = pub.get('account_id', '')
        s.commands.enqueue(
            'decision',
            {'experiment_id': exp, 'revision': rev,
             'horizon': body['horizon'], 'platform': platform,
             'account': account},
            experiment_id=exp, revision=rev, phase='collect',
            identity=f"decision:{exp}:{rev}:{body['horizon']}:"
                     f"{platform}:{account}")

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
            result=self.render(plan,node['consumers'][0],job)
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

    def render(self,plan,key,job=None):
        s=self.s; exp=s._current(plan['experiment_id'],plan['experiment_revision']); variant=s.experiments._variant(exp.experiment_id,key)
        from ..resources.runner import OwnedRunner
        s.rendering.fast.runner=OwnedRunner(s.db,Path(s.db.path).parent/'processes',variant.id,attempt=(job or {}).get('retry_count',0))
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
            speech=seg.get('speech') if isinstance(seg.get('speech'),dict) else {}
            if speech.get('normalized_copy') is not None:
                from ...script.voicetext import clean
                if clean(seg.get('copy') or '')!=speech['normalized_copy']:
                    raise ContractError('stale_speech','segment',seg['id'])
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
        # Frozen-profile mix (F20): narration+music are pre-mixed into
        # ONE deterministic artifact — measured loudness, duck envelope
        # and clip policy are bound evidence, not ad-hoc FFmpeg gains.
        profile_id=f'mix-{exp.experiment_id}-r{exp.revision}'
        if not s.mix.get(profile_id):
            s.mix.freeze(profile_id,exp.experiment_id,music.get('artifact_id',''),{
                'music_gain_db':20*math.log10(max(music.get('gain',.1),1e-6)),
                'duck':{'enabled':bool(music.get('artifact_id')),'amount_db':12,'fps':fps,
                        'regions':[{'start_frame':n['start_frame'],'end_frame':n['end_frame']} for n in narration]},
                'clip_policy':'prevent'},now=utcnow())
        tracks=[]
        for a in audio:
            kind='music' if a['id']=='music' else 'speech'
            t={'kind':kind,'offset_s':a['in_frame']/fps,
               'gain_db':20*math.log10(max(a.get('gain',1),1e-6)) if a.get('gain',1)!=1 else None,
               'trim_to_allocation':kind=='music'}
            if t['gain_db'] is None: t.pop('gain_db')
            if a.get('source_in_s',0)>0:
                from ..audio import pcm
                samples=pcm.decode(a['src'],pcm.RATE,1)
                t.update(samples=samples[round(a['source_in_s']*pcm.RATE):round(a.get('source_out_s',a['source_in_s']+(a['out_frame']-a['in_frame'])/fps)*pcm.RATE)],sample_rate=pcm.RATE)
            else:
                t['artifact_id']=a['artifact_id']
            tracks.append(t)
        mixed=s.mix.mix(profile_id,tracks,variant.target_frames/fps,artifact_name=f'{plan["id"]}:{key}')
        audio=[{'id':'mixed','kind':'audio','artifact_id':mixed['artifact_id'],'sha256':mixed['sha256'],
                'src':str(s.artifacts.verified_path(mixed['artifact_id'])),'in_frame':0,'out_frame':variant.target_frames,
                'source_in_s':0,'source_out_s':variant.target_frames/fps,'gain':1}]
        # The canvas is the draft's frozen output profile — identical for
        # all four variants, so cross-variant comparison never spans
        # dimensions. Legacy drafts without a profile pin the first
        # picture's geometry once, for this plan only.
        profile=exp.packaging.get('output_profile') or {}
        if profile.get('width') and profile.get('height'):
            clock={'fps':fps,'width':profile['width'],'height':profile['height'],'total_frames':variant.target_frames}
        else:
            source_art=s.db.uow().artifacts.get(pictures[0]['artifact_id']); probe=json.loads(source_art['probe'])
            video=next(x for x in probe['streams'] if x['codec_type']=='video')
            clock={'fps':fps,'width':video['width'],'height':video['height'],'total_frames':variant.target_frames}
        if 'run_policies' in exp.packaging:
            clock['caption_preset'] = exp.packaging['run_policies']['captions']
        # Native-quality evidence: an input smaller than the canvas is
        # upscaled by the renderer — scaling never restores detail, so
        # each upscaled input is recorded as a check limitation.
        upscaled=[]
        for p in pictures:
            part=s.db.uow().artifacts.get(p['artifact_id'])
            if not part or not part['probe']:
                continue
            pv=next((x for x in json.loads(part['probe'])['streams'] if x['codec_type']=='video'),None)
            if pv and (pv['width']<clock['width'] or pv['height']<clock['height']):
                upscaled.append(f"{p['id']}: {pv['width']}x{pv['height']} → {clock['width']}x{clock['height']}")
        renderer='hypit' if any(x.get('transition_out') not in ('cut','none','') or 'kenburns' in x.get('effects',[]) for x in pictures) else 'ffmpeg_fast'
        render_options = {}
        temporal_expected = None
        flashcut = exp.packaging.get('flashcut_policy')
        if flashcut:
            from ..templates.capabilities import renderer_order
            from .editorial_work import prepare_editorial
            from .editorial_work import output_binding
            compose=next(n for n in nodes.values() if n['kind']=='compose' and key in n['consumers'])
            if compose['request'].get('output_binding')!=output_binding(s,exp):
                raise ContractError('stale_editorial_plan','composition','Quote the changed final speech, edit plan or author package before rendering.')
            editorial_record,editorial,captions=prepare_editorial(s,exp,variant,pictures,mixed)
            pictures=[{**p,'src':str(s.artifacts.verified_path(p['artifact_id'])),
                       'frames':p['out_frame']-p['in_frame'],'media_kind':'video'} for p in editorial['pictures']]
            segments=[*editorial['pictures'],audio[0]]
            clock.update(fps_num=exp.output_clock['num'],fps_den=exp.output_clock['den'],caption_preset='phrases.v1')
            renderer = renderer_order(flashcut['renderer'])[0]
            render_options = {'renderer_policy': flashcut['renderer'], 'premix': audio[0],'native_editorial':editorial}
            quality = flashcut.get('quality') or {}
            if quality.get('technical_temporal'):
                maximum = quality['brief_event_max_frames']
                temporal_expected = {
                    'version': quality['technical_temporal'],
                    'caption_alignment': quality['caption_alignment'],
                    'brief_event_max_frames': maximum,
                    'captions': captions,
                    'passages': editorial['passages'],
                    'brief_events': [
                        {name: event[name] for name in
                         ('id', 'kind', 'required', 'start_frame', 'end_frame')}
                        for event in editorial['events']
                        if event.get('required') is True
                        and event['end_frame'] - event['start_frame'] <= maximum
                    ],
                }
        cid='comp-'+content_hash([plan['id'],key])[:24]
        result=s.composition.compile(cid,exp.experiment_id,key,plan['id'],segments,captions,clock,renderer,plan_hash=plan['plan_hash'],now=utcnow(),**render_options)
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
        final.update(composition_id=cid,build_id=bid,plan_id=plan['id'],
            experiment_revision=plan['experiment_revision'],
            mix={'profile_id':profile_id,'profile_hash':mixed['profile_hash'],
                 'measured':mixed['measured'],'artifact_id':mixed['artifact_id'],
                 'clipped':mixed['clipped']})
        if flashcut:
            final.update(editorial_plan_id=editorial_record['id'],editorial_manifest=editorial_record['manifest'])
        path=s.artifacts.verified_path(final['artifact_id']); binding=s.quality.binding(path,cid,final['artifact_id'])
        # Image artifacts placed by the authorized plan are intentional
        # stills — QC must not flag them as accidental freezes. Adjacent
        # stills merge into one interval because freezedetect reports a
        # continuous still run as a single freeze.
        stills=[]
        for p in sorted((x for x in pictures if x.get('media_kind')=='image'),key=lambda x:x['in_frame']):
            start,end=p['in_frame']/fps,p['out_frame']/fps
            if stills and start<=stills[-1]['end_s']+.05:
                stills[-1]['end_s']=end
            else:
                stills.append({'start_s':start,'end_s':end,'approved':True,'artifact_id':p['artifact_id']})
        expected={**clock,'frames':variant.target_frames,'has_audio':True,'narration':narration,'narration_required':any(seg.get('copy') for seg in variant.segments),'intentional_stills':stills,'upscaled_inputs':upscaled}
        if temporal_expected is not None:
            expected['temporal'] = temporal_expected
        tech='technical-'+bid
        if not s.quality._get(tech): s.quality.inspect(tech,path,expected,binding=binding)
        checks=[tech]
        if key!='A':
            _,a,apath,_=s._final(exp.experiment_id+':a'); regions=[]; cursor=0
            for region in sorted(variant.allowed_regions,key=lambda r:r.start):
                if region.start>cursor: regions.append({'start_frame':cursor,'end_frame':region.start})
                cursor=max(cursor,region.end)
            if cursor<variant.target_frames: regions.append({'start_frame':cursor,'end_frame':variant.target_frames})
            full_video = None
            if exp.packaging.get('run_policies', {}).get('variation') == 'full_video':
                from ..quality.variation import full_video_evidence
                full_video, regions = full_video_evidence(s, plan, variant)
            check='regions-'+bid
            if not s.quality._get(check):
                # Audio evidence comes from the deterministic mix WAVs —
                # a final's AAC transcode legitimately differs
                # sample-for-sample on identical PCM, so decoded finals
                # can never satisfy a sample-exact region compare.
                a_audio=s.artifacts.verified_path(
                    (a.get('mix') or {}).get('artifact_id')) \
                    if (a.get('mix') or {}).get('artifact_id') else None
                s.quality.check_regions(check,apath,path,regions,fps,
                    binding=binding,a_audio=a_audio,
                    b_audio=s.artifacts.verified_path(mixed['artifact_id']), full_video=full_video)
            checks.append(check)
        final.update(check_ids=checks,binding=binding)
        with s.db.uow() as u:
            u.conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',('final:'+variant.id,json.dumps(final)))
        return {'status':'rendered','variant_id':variant.id,'final':final,'review_required':True}

    # --------------------------------------------------- ownership --

    LOCK_NAME = "worker.lock"
    WORKER_VERSION = "1"

    def _acquire_process_lock(self):
        """Exclusive process lock bound to THIS database file — a second
        worker for the same DB exits cleanly instead of racing job
        claims, while a worker for a different DB (different lockfile)
        is untouched. Command-line matching is only for operators; this
        is the ownership mechanism."""
        try:
            import fcntl
        except ImportError:               # non-POSIX: no flock support
            return None
        db_path = Path(str(self.s.db.path))
        lock_path = db_path.parent / self.LOCK_NAME
        fh = open(lock_path, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.seek(0)
            holder = fh.read().strip() or "unknown"
            fh.close()
            raise ContractError(
                "worker_already_running", "lock",
                f"{lock_path} held by {holder}")
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({
            "pid": os.getpid(), "worker_id": self.scheduler.worker_id,
            "db": str(db_path), "version": self.WORKER_VERSION,
            "acquired_at": utcnow()}))
        fh.flush()
        return fh                        # keep the fd open for life

    def run(self,once=False):
        lock = self._acquire_process_lock()
        # A racing writer (e.g. the API still finishing startup) can make
        # BEGIN IMMEDIATE lose the lock. That is transient contention, not
        # a dead worker — back off bounded instead of dying on the first
        # tick. Persistent lock failure still surfaces after ~2 minutes.
        locked = 0
        while True:
            try:
                result=self.tick()
            except sqlite3.OperationalError as error:
                if 'locked' not in str(error): raise
                locked += 1
                if locked > 40: raise
                time.sleep(min(0.25 * 2 ** min(locked, 7), 30))
                continue
            locked = 0
            if once: return result
            if result is None: time.sleep(.25)
