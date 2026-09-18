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
        platform=body.get('platform','')
        metadata=dict(body.get('metadata',{}));mp_id='';mp_rev=0
        if body.get('metadata_package_id'):
            mp=s.detail('metadatapackage',body['metadata_package_id'])
            if mp['status']!='frozen':raise ContractError('metadata_not_frozen','metadata_package_id')
            if mp['variant_plan_id']!=v['id']:raise ContractError('metadata_variant_mismatch','metadata_package_id')
            if mp['platform']!=platform:raise ContractError('metadata_platform_mismatch','metadata_package_id')
            if mp['final_sha256'] and mp['final_sha256']!=final['sha256']:raise ContractError('metadata_stale','metadata_package_id')
            metadata={**(mp.get('selected') or {}),**metadata,'disclosures':mp.get('disclosures') or {}}
            mp_id=mp['id'];mp_rev=mp.get('revision',0)
        p=s.publishing.plan('pub-'+uuid.uuid4().hex,variant_plan_id=v['id'],final_sha256=final['sha256'],artifact_id=final['artifact_id'],
            platform=platform,account_id=body.get('account_id',''),metadata=metadata,
            visibility=body.get('visibility','public'),scheduled_at=body.get('scheduled_at',''),tz=body.get('timezone','UTC'),horizon_policy=policy,
            experiment_id=v['experiment_id'],experiment_revision=v['experiment_revision'],
            provider=body.get('provider','upload_post'),connection_id=body.get('connection_id',''),
            metadata_package_id=mp_id,metadata_revision=mp_rev)
        # Persist the review evidence the external effect must still
        # satisfy — acceptance is revalidated at execution time, so a
        # withdrawn or superseded review can never publish.
        row=s.db.uow().records.get('publicationintent','intent:'+p.id)
        saved=json.loads(row['body'])
        saved.update(check_ids=list(body.get('check_ids') or []),binding=binding)
        with s.db.uow() as u:
            u.conn.execute("UPDATE records SET body=? WHERE kind='publicationintent' AND id=? AND revision=?",(json.dumps(saved),'intent:'+p.id,row['revision']))
        return p.to_dict()

    def plan_batch(self,experiment_id,body,revision):
        """One publication plan per (variant × destination) — up to
        sixteen slots, each an independent durable intent (PL-03)."""
        s=self.s;dests=body.get('destinations') or []
        if not dests:raise ContractError('destinations_required','destinations')
        variants=[json.loads(r['body']) for r in s.db.conn.execute(
            "SELECT body FROM records WHERE kind='variantplan' AND json_extract(body,'$.experiment_id')=? AND json_extract(body,'$.experiment_revision')=?",(experiment_id,revision)).fetchall()]
        if not variants:raise ContractError('not_found','experiment')
        out=[];errors=[]
        for v in variants:
            for d in dests:
                slot=dict(body);slot.update(d)
                slot.pop('destinations',None);slot.pop('variants',None)
                if not slot.get('metadata_package_id'):
                    mp=self._frozen_package(v['id'],d.get('platform',''))
                    if mp:slot['metadata_package_id']=mp['id']
                if not slot.get('check_ids'):
                    try:
                        slot['check_ids']=self._bound_check_ids(v)
                    except ContractError as e:
                        errors.append({'variant':v['variant_key'],
                                       'platform':d.get('platform',''),
                                       'code':e.code,'detail':e.detail})
                        continue
                try:
                    out.append(self.plan(v['id'],slot,revision))
                except ContractError as e:
                    errors.append({'variant':v['variant_key'],
                                   'platform':d.get('platform',''),
                                   'code':e.code,'detail':e.detail})
        return {'publications':out,'errors':errors,
                'slots':len(variants)*len(dests)}

    def _frozen_package(self, variant_id, platform):
        """Frozen metadata package for (variant, platform) — attached
        automatically when the batch slot doesn't name one."""
        rows = self.s.db.conn.execute(
            "SELECT body FROM records WHERE kind='metadatapackage'"
            " AND json_extract(body,'$.variant_plan_id')=?"
            " AND json_extract(body,'$.platform')=?"
            " AND json_extract(body,'$.status')='frozen'"
            " ORDER BY json_extract(body,'$.revision') DESC",
            (variant_id, platform)).fetchall()
        return json.loads(rows[0][0]) if rows else None

    def _bound_check_ids(self, v):
        """Review ids bound to this variant's current final — the batch
        caller cannot know per-variant ids, so each slot derives them."""
        s=self.s;_,final,_,binding=s._final(v['id'])
        rows=s.db.conn.execute(
            "SELECT body FROM records WHERE kind='review'").fetchall()
        return [json.loads(r[0])['id'] for r in rows
                if json.loads(r[0]).get('binding')==binding
                and json.loads(r[0]).get('target_hash')==final['sha256']
                and not json.loads(r[0]).get('invalidated_by')]

    def authorize(self,pid,body):
        s=self.s;p=s.publishing.get(pid)
        if not p:raise ContractError('not_found','publication')
        intent=s.detail('publicationintent','intent:'+pid)
        if body.get('final_sha256')!=p['final_sha256'] or body.get('platform')!=p['platform'] or body.get('account_id')!=p['account_id'] or body.get('action')!='publish' or not body.get('reviewer'):
            raise ContractError('publication_scope_mismatch','approval')
        provider=p.get('provider') or 'upload_post'
        auth=Authorization(schema_version='authorization.v1',id='publish-auth-'+uuid.uuid4().hex,created_at=utcnow(),status='authorized',scope_hash=intent['plan_hash'],
            publication_authorized=True,allowed_providers=[provider],allowed_models={provider:['upload']},valid_until=body.get('valid_until',''),authorizing_action=body['reviewer'])
        EffectService(s.db,s.executor).approve(auth,'publicationintent',intent['id'],[dict(key='publish',kind='publication',provider=provider,model='upload',account=p['account_id'],request=intent['request'])],[])
        s.publishing.authorize(pid,auth.id)
        return {'authorization_id':auth.id,'publication_id':pid}

    def queue(self,pid):
        s=self.s;p=s.publishing.get(pid)
        if not p:raise ContractError('not_found','publication')
        s.publishing._check_authorization(p,utcnow())
        if s.publishing.publisher is None:raise ContractError('publication_route_unqualified','publisher')
        gate=self._loop_gate(p)
        if gate=='paused':raise ContractError('loop_paused','series_id')
        if gate:raise ContractError(gate,'publication',pid)
        v=s.detail('variantplan',p['variant_plan_id'])
        return s.commands.enqueue('publish',{'publication_id':pid},experiment_id=v['experiment_id'],revision=v['experiment_revision'],identity='publish:'+pid)

    def _loop_gate(self,p):
        """Series policy gate on dispatch (§10): a paused loop holds
        queued work ('defer' — resumable), a revoked/expired loop
        blocks it, and declared provider/account allow-lists are
        enforced against the slot. Returns a ContractError code or
        'paused', or None when no policy governs this publication."""
        rounds=getattr(self.s,'rounds',None)
        exp=p.get('experiment_id')
        if rounds is None or not exp:return None
        try:series_id,_,_=rounds._series_id(exp)
        except ContractError:return None
        pol=rounds._loop_policy(series_id)
        if pol is None:return None
        st=pol.get('status')
        if st=='paused':return 'paused'
        if st and st!='active':return 'loop_halted:'+st
        if st=='active':
            ap=pol.get('allowed_providers') or []
            if ap and p.get('provider','upload_post') not in ap:
                return 'provider_not_allowed'
            aa=pol.get('allowed_accounts') or []
            if aa and p.get('account_id') not in aa:
                return 'account_not_allowed'
        return None

    def execute(self,body,job):
        s=self.s;p=s.publishing.get(body['publication_id'])
        if not p:raise ContractError('not_found','publication')
        def grant(request,*unused):
            aid=EffectService(s.db,s.executor).prepare(p['authorization_id'],'publish',job['id'],job['fencing_token'],s.scheduler.worker_id)
            s.executor.require_request(aid,request);return aid
        s.publishing.effects=grant
        path=s.artifacts.verified_path(p['artifact_id'])
        # Final gate before the external effect: the creative review must
        # still pass against these bytes — a review withdrawn, superseded
        # or invalidated since queueing blocks publication truthfully.
        intent=s.detail('publicationintent','intent:'+p['id']) or {}
        check_ids=intent.get('check_ids');bind=intent.get('binding')
        if check_ids is None or bind is None:
            meta=s.db.conn.execute("SELECT value FROM meta WHERE key=?",('final:'+p['variant_plan_id'],)).fetchone()
            stored=json.loads(meta[0]) if meta else {}
            check_ids=stored.get('check_ids',[]) if check_ids is None else check_ids
            bind=stored.get('binding') if bind is None else bind
        s.quality.accept(path,check_ids,bind)
        # Series policy governs dispatch (§10): a paused loop holds the
        # job for a later claim — it does not die; a revoked/expired
        # loop or a disallowed provider/account blocks it outright.
        gate=self._loop_gate(p)
        if gate=='paused':
            return {'status':'pending','defer_s':600,
                    'loop':'paused'}
        if gate:raise ContractError(gate,'publication',p['id'])
        out=s.publishing.publish(p['id'],video_path=str(path))
        if out['status']=='scheduled':
            # A remotely-scheduled post is not terminal — a durable
            # observation job polls it into public so checkpoints can
            # be created (the observe job self-defers until the remote
            # fires or its bound is exhausted).
            when=out.get('scheduled_at') or p.get('scheduled_at') or ''
            s.commands.enqueue('publication_observe',
                {'publication_id':p['id']},
                identity=f"observe:{p['id']}:scheduled",
                not_before=when or None,phase='collect',
                experiment_id=p.get('experiment_id',''),
                revision=p.get('experiment_revision',0))
            return {'status':'complete','publication':out}
        if out['status'] in ('uploading','processing','unknown'):
            with s.db.uow() as u:u.conn.execute("UPDATE jobs SET phase='collect' WHERE id=?",(job['id'],))
            return {'status':'pending','publication':out}
        if out['status']=='failed':raise ContractError('publication_failed','publication',p['id'])
        return {'status':'complete','publication':out}
