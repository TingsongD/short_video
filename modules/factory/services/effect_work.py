"""Immutable, quoted research/audio/analysis work and durable approved jobs."""
from dataclasses import dataclass,field
from datetime import datetime,timezone
import json
import uuid
from ..domain.records import Record,Authorization,PriceAssessment,content_hash
from ..domain.errors import ContractError
from ..execution.effects import EffectService,wire_hash
from ..store.uow import utcnow

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

    def prepare(self,kind,provider,model,requests,experiment_id='',revision=0):
        if kind not in ('research','tts','music','analysis'):raise ContractError('invalid_effect_kind','kind')
        adapter=self.s.providers.get(provider)
        if adapter is None or not getattr(adapter,'account',None):raise ContractError('route_unavailable','provider',provider)
        if not requests or len(requests)>20 or any(not isinstance(x,dict) for x in requests):raise ContractError('invalid_requests','operations')
        if experiment_id:self.s._current(experiment_id,revision,True)
        operations=[];totals={}
        for i,request in enumerate(requests):
            request=dict(request)
            if request.get("model",model)!=model:raise ContractError("model_mismatch","model")
            from ..events.redact import redact
            if redact(request)!=request:raise ContractError('sensitive_request','request')
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
        plan=EffectPlan(schema_version='effect_plan.v1',id='effect-'+uuid.uuid4().hex,created_at=utcnow(),
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
        prior=s.db.conn.execute('SELECT id,status FROM attempts WHERE job_id=?',(job['id'],)).fetchone()
        aid=prior['id'] if prior and prior['status']!='prepared' else effect.prepare(body['authorization_id'],body['operation'],job['id'],job['fencing_token'],s.scheduler.worker_id)
        if prior and prior['status'] in ('unknown','dispatching'):out=s.executor.reconcile(aid) or {'status':'unknown'}
        elif prior and prior['status']!='prepared':out=s.executor.poll(aid)
        else:out=s.executor.submit(aid)
        if out.get('status') in ('accepted','running','unknown'):
            with s.db.uow() as u:u.conn.execute("UPDATE jobs SET phase='collect' WHERE id=?",(job['id'],))
            return {'status':'pending','attempt_id':aid}
        if out.get('status')!='succeeded':raise ContractError('effect_failed','attempt',aid)
        operation=next(op for op in plan['operations'] if op['key']==body['operation'])
        actual=out.get('actual_usd_micros') if operation['price']['unit']=='usd_micros' else out.get('actual_credits')
        if type(actual) is int:effect.settle(aid,actual,'reported_usage',out.get('operation_id') or aid)
        result={'status':'succeeded','attempt_id':aid,'result':out.get('result',{}),'charge_verified':type(actual) is int}
        if plan['kind'] in ('tts','music'):
            media=s.executor.download(aid)
            artifact=s.artifacts.intake_bytes(media['bytes'],provenance='elevenlabs' if plan['provider']=='elevenlabs' else 'generated_other',source_key=aid,requested_kind='audio')
            result.update(artifact_id=artifact.id,sha256=artifact.sha256,alignment=media.get('alignment'))
        return result
