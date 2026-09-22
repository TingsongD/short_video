"""Immutable, quoted research/audio/analysis work and durable approved jobs."""
from dataclasses import dataclass,field
from datetime import datetime,timezone
import json
import uuid
from ..domain.records import Record,Authorization,PriceAssessment,content_hash
from ..domain.errors import ContractError
from ..execution.effects import EffectService,wire_hash
from ..store.uow import utcnow
from ..testing.fakes import ProviderError

@dataclass
class EffectPlan(Record):
    kind:str=''
    provider:str=''
    model:str=''
    account:str=''
    experiment_id:str=''
    experiment_revision:int=0
    operations:list=field(default_factory=list)
    plan_hash:str=''
    total:dict=field(default_factory=dict)


class EffectWork:
    def __init__(self,services):self.s=services

    def prepare(self,kind,provider,model,requests,experiment_id='',revision=0,plan_id='',valid_until=''):
        if kind not in ('research','tts','music','analysis','generation'):raise ContractError('invalid_effect_kind','kind')
        adapter=self.s.providers.get(provider)
        if adapter is None or not getattr(adapter,'account',None):raise ContractError('route_unavailable','provider',provider)
        if not requests or len(requests)>20 or any(not isinstance(x,dict) for x in requests):raise ContractError('invalid_requests','operations')
        if experiment_id:self.s._current(experiment_id,revision,True)
        if plan_id:
            # Content-keyed plans are get-or-create: a caller that crashes
            # after this commit and retries must land on the same plan, not
            # mint a second paid scope.
            prior=self.s.db.uow().records.get('effectplan',plan_id)
            if prior:
                body=json.loads(prior['body'])
                same=(body.get('kind')==kind and body.get('provider')==provider
                    and body.get('model')==model
                    and body.get('experiment_id','')==experiment_id
                    and body.get('experiment_revision',0)==revision
                    and [op.get('request') for op in body.get('operations',[])]==list(requests))
                if not same:raise ContractError('plan_id_conflict','plan_id')
                return body
        operations=[];totals={}
        for i,request in enumerate(requests):
            request=dict(request)
            if request.get("model",model)!=model:raise ContractError("model_mismatch","model")
            from ..events.redact import redact
            if redact(request)!=request:raise ContractError('sensitive_request','request')
            if kind == 'generation':
                if not valid_until:
                    raise ContractError('quote_expiry_required', 'valid_until')
                if self.s.production.router:
                    self.s.production.router.preflight(provider, model, request, request['duration_s'], experiment_id)
                if hasattr(adapter, 'prepare_quote'):
                    native = adapter.prepare_quote(request)
                    amount, unit = native['max_credits'], 'jimeng_credits'
                    basis = {k: v for k, v in native.items() if k != 'prep'}
                else:
                    native = adapter.price(request, request['duration_s'], model)
                    money = native.to_dict() if hasattr(native, 'to_dict') else native
                    amount, unit = money['amount'], money['unit']
                    basis = {'kind': 'configured_generation_estimate', 'model': model, 'duration_s': request['duration_s']}
                price = {'kind': 'usage_estimate' if provider == 'google_vertex' else 'native_quote',
                         'unit': unit, 'amount': amount, 'reserve_amount': amount,
                         'rate_basis': json.dumps(basis, sort_keys=True), 'valid_until': valid_until}
            else:
                price=adapter.price(request)
            if not isinstance(price,dict) or not {'kind','unit','amount','reserve_amount','rate_basis','valid_until'}<=price.keys():raise ContractError('pricing_unavailable','price')
            # Pricing comes from the configured adapter snapshot, never from
            # caller-supplied amounts or an implicit zero estimate.
            quote=PriceAssessment(schema_version='price_assessment.v1',id='check-'+str(i),created_at=utcnow(),
                kind=price['kind'],provider=provider,model=model,request_hash=wire_hash(request),
                unit=price['unit'],amount=price['amount'],reserve_amount=price['reserve_amount'],
                rate_basis=price['rate_basis'],valid_until=price['valid_until'],provisional=price.get('provisional',False))
            quote.validate_or_raise()
            if datetime.fromisoformat(quote.valid_until.replace('Z','+00:00'))<=datetime.now(timezone.utc):raise ContractError('quote_expired','price')
            totals[quote.unit]=totals.get(quote.unit,0)+quote.reserve_amount
            operations.append({'key':str(i),'request':request,'price':quote.to_dict()})
        plan=EffectPlan(schema_version='effect_plan.v1',id=plan_id or 'effect-'+uuid.uuid4().hex,created_at=utcnow(),
            kind=kind,provider=provider,model=model,account=adapter.account,experiment_id=experiment_id,
            experiment_revision=revision,operations=operations,total=totals)
        plan.plan_hash=content_hash(plan.to_dict());plan.validate_or_raise()
        with self.s.db.uow() as u:u.records.put(plan)
        return plan.to_dict()

    def get(self,pid):return self.s.detail('effectplan',pid)

    def authorize(self,pid,body):
        plan=self.get(pid)
        if not body.get('reviewer') or body.get('plan_hash')!=plan['plan_hash']:raise ContractError('approval_mismatch','plan_hash/reviewer')
        auth=Authorization(schema_version='authorization.v1',id='auth-'+uuid.uuid4().hex,created_at=utcnow(),status='authorized',
            scope_hash=plan['plan_hash'],allowed_providers=[plan['provider']],allowed_models={plan['provider']:[plan['model']]},
            caps=body.get('ceilings',{}),valid_until=body.get('valid_until',''),authorizing_action=body['reviewer'])
        operations=[]
        for op in plan['operations']:
            q=PriceAssessment(**{**op['price'],'id':'price-'+uuid.uuid4().hex,'plan_hash':plan['plan_hash']})
            operations.append(dict(key=op['key'],kind=plan['kind'],provider=plan['provider'],model=plan['model'],account=plan['account'],request=op['request'],price=q))
        EffectService(self.s.db,self.s.executor).approve(auth,'effectplan',pid,operations,body.get('budget_ids',[]))
        return {'authorization_id':auth.id,'plan_hash':plan['plan_hash']}

    def queue(self,pid,authority):
        plan=self.get(pid);auth=EffectService(self.s.db,self.s.executor)._scope(authority)
        if auth.binding['id']!=pid:raise ContractError('approval_mismatch','authorization_id')
        return {'plan_id':pid,'jobs':[self.s.commands.enqueue('effect',{'plan_id':pid,'authorization_id':authority,'operation':op['key']},
            experiment_id=plan['experiment_id'],revision=plan['experiment_revision'],phase='analyze',identity=pid+':'+op['key']) for op in plan['operations']]}

    def execute(self,body,job):
        s=self.s;plan=self.get(body['plan_id']);adapter=s.providers.get(plan['provider'])
        if adapter is None:raise ContractError('route_unavailable','provider')
        s.executor.provider=adapter
        effect=EffectService(s.db,s.executor)
        operation=next(op for op in plan['operations'] if op['key']==body['operation'])
        cache_key=None
        if plan['kind']=='research':
            # Durable cache BEFORE intent/attempt/reservation — an
            # identical research request must never re-charge.
            cache_key=content_hash({'provider':plan['provider'],'account':plan['account'],
                                    'request':operation['request'],'query_version':'creator-history.v2'})
            cached=s.db.conn.execute("SELECT body,observed_at FROM discovery_cache WHERE query_key=? AND page=?",
                (cache_key,operation['request'].get('page',1))).fetchone()
            if cached:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached['observed_at'].replace('Z','+00:00'))).total_seconds()
                if 0<=age<86400:
                    return {'status':'succeeded','attempt_id':'','result':{'posts':json.loads(cached['body'])},
                            'cache_hit':True,'charge_verified':True}
        prior=self._latest_attempt(job['id'])
        if plan['kind'] == 'analysis' and prior and prior['status'] == 'failed' and not prior['remote_id']:
            # A previous worker may have persisted the failed status before
            # releasing its hold. Only an exact durable rejection receipt can
            # finish that accounting transition; absence of a remote id cannot.
            from ..execution.context import dispatch_context
            with dispatch_context({'attempt_id': prior['id']}):
                receipt = adapter.reconcile(request_hash=prior['request_hash'])
            s.executor._resolve_throttle(prior['id'], receipt)
        if plan['kind'] == 'generation' and (not prior or prior['status'] == 'prepared') and s.production.router:
            # Qualification may expire while queued. Recheck only before
            # submission; observation of existing remote work stays possible.
            s.production.router.preflight(plan['provider'], plan['model'], operation['request'],
                                          operation['request']['duration_s'], plan['experiment_id'])
        from ..execution.throttle import rejection, wait_seconds
        retrying = plan['kind'] == 'analysis' and rejection(s.db, prior)
        if retrying:
            delay = wait_seconds(s.db, prior, s.scheduler.clock())
            if delay is None:
                raise ContractError('analysis_throttle_exhausted', 'job_id', job['id'])
            if delay > 0:
                return {'status': 'pending', 'reason': 'analysis_throttled', 'defer_s': delay, 'attempt_id': prior['id']}
            # A distinct attempt/receipt and a fresh reservation, still bound
            # to this exact unexpired quote and authority. Never reset the
            # rejected attempt or count it as successful QC.
            aid = effect.prepare(body['authorization_id'], body['operation'], job['id'], job['fencing_token'],
                                 s.scheduler.worker_id, attempt_seq=prior['attempt_seq'] + 1)
            prior = None
        else:
            aid=prior['id'] if prior and prior['status']!='prepared' else effect.prepare(body['authorization_id'],body['operation'],job['id'],job['fencing_token'],s.scheduler.worker_id)
        if prior and prior['status'] in ('unknown','dispatching'):out=s.executor.reconcile(aid) or {'status':'unknown'}
        elif prior and prior['status']!='prepared':out=s.executor.poll(aid)
        else:
            try:
                out=s.executor.submit(aid)
            except ProviderError:
                current = s.executor._attempt(aid)
                if plan['kind'] != 'analysis' or not rejection(s.db, current):
                    raise
                delay = wait_seconds(s.db, current, s.scheduler.clock())
                if delay is None:
                    raise ContractError('analysis_throttle_exhausted', 'job_id', job['id']) from None
                return {'status': 'pending', 'reason': 'analysis_throttled', 'defer_s': delay, 'attempt_id': aid}
        if plan['kind'] == 'analysis' and out.get('status') == 'failed':
            current = s.executor._attempt(aid)
            if rejection(s.db, current):
                delay = wait_seconds(s.db, current, s.scheduler.clock())
                if delay is None:
                    raise ContractError('analysis_throttle_exhausted', 'job_id', job['id'])
                return {'status': 'pending', 'reason': 'analysis_throttled', 'defer_s': delay, 'attempt_id': aid}
        if out.get('status') in ('accepted','running','unknown'):
            with s.db.uow() as u:u.conn.execute("UPDATE jobs SET phase='collect' WHERE id=?",(job['id'],))
            return {'status':'pending','attempt_id':aid}
        if out.get('status')!='succeeded':raise ContractError('effect_failed','attempt',aid)
        actual=out.get('actual_usd_micros') if operation['price']['unit']=='usd_micros' else out.get('actual_credits')
        if type(actual) is int:effect.settle(aid,actual,'reported_usage',out.get('operation_id') or aid)
        result={'status':'succeeded','attempt_id':aid,'result':out.get('result',{}),'charge_verified':type(actual) is int}
        if cache_key is not None:
            # Write-through: the durable receipt that lets every later
            # identical request skip the paid/provider call entirely.
            posts=(out.get('result') or {}).get('posts',[])
            with s.db.uow() as u:
                u.conn.execute("INSERT OR REPLACE INTO discovery_cache(query_key,page,body,observed_at,run_id) VALUES(?,?,?,?,?)",
                    (cache_key,operation['request'].get('page',1),json.dumps(posts),utcnow(),body['plan_id']))
        if plan['kind'] in ('tts','music','generation'):
            media=s.executor.download(aid)
            provenance = 'elevenlabs' if plan['provider']=='elevenlabs' else 'generated_other'
            if plan['kind'] == 'generation' and operation['request'].get('workflow_version') == 2:
                provenance = plan['provider']
            artifact=s.artifacts.intake_bytes(media['bytes'],provenance=provenance,source_key=aid,requested_kind='video' if plan['kind']=='generation' else 'audio')
            result.update(artifact_id=artifact.id,sha256=artifact.sha256,alignment=media.get('alignment'))
        return result

    def _latest_attempt(self, job_id):
        row = self.s.db.conn.execute('SELECT id FROM attempts WHERE job_id=? ORDER BY attempt_seq DESC LIMIT 1', (job_id,)).fetchone()
        return self.s.executor._attempt(row['id']) if row else None

    def resume_throttled_job(self, job_id):
        """Recover a paused pre-patch 429 job, never an arbitrary failed job."""
        from ..execution.throttle import wait_seconds
        with self.s.db.uow() as u:
            job = u.jobs.get(job_id)
            if not job or job['status'] not in {'failed', 'blocked'} or job['blocked_reason'] != 'analysis_http_error':
                return False
            command = u.records.get('appcommand', job_id)
            body = json.loads(command['body']) if command else {}
            if body.get('kind') != 'effect' or self.get(body['input']['plan_id'])['kind'] != 'analysis':
                return False
            attempt = self._latest_attempt(job_id)
            if wait_seconds(self.s.db, attempt, self.s.scheduler.clock()) is None:
                return False
            # The worker revalidates account, quote, authority, budget, fencing
            # and backoff before any new request. No funds are released here.
            u.conn.execute("UPDATE jobs SET status='waiting_dependencies',lease_owner=NULL,lease_expires=NULL,next_attempt_at=NULL,blocked_reason=NULL WHERE id=?", (job_id,))
            u.events.append('factory', 'analysis_throttle_recovery_queued', {'job_id': job_id, 'rejected_attempt': attempt['id']})
        return True
