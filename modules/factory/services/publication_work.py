"""Application publication commands bound to reviewed, delivered final bytes."""
import json,uuid
from ..domain.errors import ContractError
from ..domain.records import Authorization,content_hash
from ..execution.effects import EffectService
from ..store.uow import utcnow


class PublicationWork:
    def __init__(self,s):self.s=s

    def plan(self,variant_id,body,revision):
        s=self.s;v,final,path,binding=s._final(variant_id)
        s._current(v['experiment_id'],revision,True)
        s.quality.accept(path,body.get('check_ids',[]),binding)
        receipts=s.db.conn.execute("SELECT body FROM records WHERE kind='delivery' AND json_extract(body,'$.file_sha256')=? AND json_extract(body,'$.status')='verified'",(final['sha256'],)).fetchall()
        if not any(json.loads(r[0]).get('variant_plan_id')==v['id'] and json.loads(json.loads(r[0]).get('cleanup_receipt') or '{}').get('state')=='verified' for r in receipts):raise ContractError('verified_delivery_required','final')
        policy=s.learning.policy(v['experiment_id'],v['experiment_revision'])
        if not policy:raise ContractError('policy_not_frozen','experiment')
        if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
        p=s.publishing.plan('pub-'+uuid.uuid4().hex,variant_plan_id=v['id'],final_sha256=final['sha256'],artifact_id=final['artifact_id'],
            platform=body.get('platform',''),account_id=body.get('account_id',''),metadata=body.get('metadata',{}),
            visibility=body.get('visibility','public'),scheduled_at=body.get('scheduled_at',''),tz=body.get('timezone','UTC'),horizon_policy=policy,
            experiment_id=v['experiment_id'],experiment_revision=v['experiment_revision'])
        return p.to_dict()

    def authorize(self,pid,body):
        s=self.s;p=s.publishing.get(pid)
        if not p:raise ContractError('not_found','publication')
        intent=s.detail('publicationintent','intent:'+pid)
        if body.get('final_sha256')!=p['final_sha256'] or body.get('platform')!=p['platform'] or body.get('account_id')!=p['account_id'] or body.get('action')!='publish' or not body.get('reviewer'):
            raise ContractError('publication_scope_mismatch','approval')
        auth=Authorization(schema_version='authorization.v1',id='publish-auth-'+uuid.uuid4().hex,created_at=utcnow(),status='authorized',scope_hash=intent['plan_hash'],
            publication_authorized=True,allowed_providers=['upload_post'],allowed_models={'upload_post':['upload']},valid_until=body.get('valid_until',''),authorizing_action=body['reviewer'])
        EffectService(s.db,s.executor).approve(auth,'publicationintent',intent['id'],[dict(key='publish',kind='publication',provider='upload_post',model='upload',account=p['account_id'],request=intent['request'])],[])
        s.publishing.authorize(pid,auth.id)
        return {'authorization_id':auth.id,'publication_id':pid}

    def queue(self,pid):
        s=self.s;p=s.publishing.get(pid)
        if not p:raise ContractError('not_found','publication')
        s.publishing._check_authorization(p,utcnow())
        if s.publishing.publisher is None:raise ContractError('publication_route_unqualified','publisher')
        v=s.detail('variantplan',p['variant_plan_id'])
        return s.commands.enqueue('publish',{'publication_id':pid},experiment_id=v['experiment_id'],revision=v['experiment_revision'],identity='publish:'+pid)

    def execute(self,body,job):
        s=self.s;p=s.publishing.get(body['publication_id'])
        if not p:raise ContractError('not_found','publication')
        def grant(request,*unused):
            aid=EffectService(s.db,s.executor).prepare(p['authorization_id'],'publish',job['id'],job['fencing_token'],s.scheduler.worker_id)
            s.executor.require_request(aid,request);return aid
        s.publishing.effects=grant
        path=s.artifacts.verified_path(p['artifact_id'])
        out=s.publishing.publish(p['id'],video_path=str(path))
        if out['status'] in ('uploading','processing','unknown'):
            with s.db.uow() as u:u.conn.execute("UPDATE jobs SET phase='collect' WHERE id=?",(job['id'],))
            return {'status':'pending','publication':out}
        if out['status']=='failed':raise ContractError('publication_failed','publication',p['id'])
        return {'status':'complete','publication':out}
