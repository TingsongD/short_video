"""Application commands over authoritative domain records and durable worker jobs."""
import copy
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import Authorization, ProductSnapshot, ProviderPolicy, content_hash
from ..events.redact import redact
from ..store.uow import utcnow
from .commands import CommandQueue

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {"mp4", "mov", "webm", "png", "jpg", "jpeg", "mp3", "wav", "m4a"}
COLLECTIONS = {"seeds":"seed", "blueprints":"referenceblueprint", "templates":"formattemplate",
    "products":"productsnapshot", "experiments":"experimentrevision", "variants":"variantplan",
    "plans":"productionplan", "compositions":"composition", "reviews":"review", "deliveries":"delivery",
    "publications":"publication", "decisions":"decision",'research':'discoveryrun','effect_plans':'effectplan','metrics':'metricsnapshot','policies':'decisionpolicy','analyses':'referenceanalysis',
    'metadatapackages':'metadatapackage','checkpoints':'checkpointschedule','selections':'seedselection','lineages':'roundlineage','loops':'looppolicy'}


class FactoryServices:
    def __init__(self, db, seeds=None, experiments=None, scheduler=None, artifacts=None,
                 quality=None, delivery=None, executor=None, providers=None, artifact_root="",
                 analysis=None, blueprints=None, templates=None, production=None, composition=None,
                 rendering=None, resources=None, cleanup=None, studio=None, config=None):
        self.db, self.seeds, self.experiments = db, seeds, experiments
        self.scheduler, self.artifacts, self.quality = scheduler, artifacts, quality
        self.delivery, self.executor, self.providers = delivery, executor, providers or {}
        self.analysis, self.blueprints, self.templates = analysis, blueprints, templates
        self.production, self.composition, self.rendering = production, composition, rendering
        self.resources, self.cleanup, self.studio = resources, cleanup, studio
        self.config = config or {}
        self.commands = CommandQueue(db, scheduler) if scheduler else None

    def require(self, name):
        svc = getattr(self, name, None)
        if svc is None:
            raise ContractError("unavailable", name, "service is not configured; see readiness")
        return svc

    def health(self):
        self.db.conn.execute("SELECT 1").fetchone()
        row = self.db.conn.execute("SELECT value FROM meta WHERE key='worker_heartbeat'").fetchone()
        beat = json.loads(row[0]) if row else None
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(beat['at'].replace('Z','+00:00'))).total_seconds() if beat else None
        return {"api":"ok", "storage":"ok", "worker":{"available": age is not None and age < 150,
            "heartbeat":beat, "paused":bool(self.scheduler and self.scheduler.paused),
            "draining":bool(self.scheduler and self.scheduler._flag('draining'))}, "mode":self.config.get('mode','offline')}

    def providers_readiness(self,refresh=False):
        # Readiness checks can spawn subprocesses — cache per-process for
        # 60s so dashboard refreshes never run them synchronously; an
        # explicit refresh bypasses the cache.
        if not refresh and getattr(self,'_readiness_cache',None) is not None \
                and time.monotonic()-self._readiness_at<60:
            return self._readiness_cache
        out = {name:{'installed':False,'authenticated':False,'catalog_visible':False,'contract_tested':False,'live_qualified':False,'tested':False,'qualified':False,'detail':{'reason':'Route not configured and currently qualified; use imports or complete the recorded qualification gate'}} for name in ('jimeng_canvas','google_vertex','elevenlabs','generated_music','audiovisual_analysis')}
        for name, adapter in self.providers.items():
            try:
                ready = adapter.readiness()
            except Exception as error:
                ready = {"error":type(error).__name__}
            out[name] = {k: ready.get(k) is True for k in ('installed','authenticated','catalog_visible','contract_tested','live_qualified')}
            out[name]['tested'] = out[name]['contract_tested']
            out[name]['qualified'] = out[name]['live_qualified']
            out[name]['detail'] = redact(ready)
        self._readiness_cache=out;self._readiness_at=time.monotonic()
        return out

    def collection(self, name):
        if name=='budgets':
            from ..budget import BudgetService
            ledger=BudgetService(self.db)
            return [{**dict(r),'retired':bool(self.db.conn.execute('SELECT 1 FROM meta WHERE key=?',('retired:budget:'+r['id'],)).fetchone()),'available':ledger.available(r['id'])} for r in self.db.conn.execute('SELECT * FROM budgets')]
        if name == 'queue':
            return self.require('scheduler').status_snapshot()
        if name == 'assets':
            return [json.loads(r['body']) for r in self.db.conn.execute('SELECT body FROM artifacts ORDER BY created_at DESC')]
        kind = COLLECTIONS.get(name)
        if not kind:
            raise ContractError('not_found','collection',name)
        # `version` is the optimistic-lock row handle used by in-place
        # CAS mutations (e.g. metadata select/freeze); `revision` in the
        # body is the record's own version identity.
        return [{**json.loads(r['body']), 'version': r['version']}
                for r in self.db.conn.execute(
            "SELECT r.body, r.version FROM records r WHERE kind=? AND revision=(SELECT MAX(revision) FROM records x WHERE x.kind=r.kind AND x.id=r.id) ORDER BY created_at DESC", (kind,))]

    def detail(self, kind, rid):
        row = self.db.uow().records.get(kind, rid)
        if not row:
            raise ContractError('not_found','id',rid)
        return json.loads(row['body'])

    def get_seed(self, seed_id):
        return self.require('seeds').get(seed_id).to_dict()

    def create_seed(self, url, via='api'):
        seed, created = self.require('seeds').submit_url(url, via=via)
        return {'seed':seed.to_dict(),'created':created}

    def attach_media(self, seed_id, artifact_id):
        self.require('artifacts').verified_path(artifact_id)
        return self.require('seeds').attach_media(seed_id, artifact_id)[0].to_dict()

    def import_file(self, filename, data=None, path=None):
        ext = filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
        if ext not in ALLOWED_UPLOAD_TYPES:
            raise ContractError('bad_type','filename',f'.{ext} not importable')
        size = Path(path).stat().st_size if path else len(data)
        if size > MAX_UPLOAD_BYTES:
            raise ContractError('too_large','size')
        store = self.require('artifacts')
        if path:
            return store.intake_file(path, provenance='manual', source_key='import:'+filename, source_detail=filename).to_dict()
        return store.intake_bytes(data, provenance='manual', source_key='import:'+hashlib.sha256(data).hexdigest(), source_detail=filename).to_dict()

    def analyze_seed(self, seed_id, body):
        self.get_seed(seed_id)
        if 'observations' not in body:
            raise ContractError('analysis_route_unqualified','observations','Import reviewed observations, or qualify and authorize an analysis adapter')
        if not body.get('reviewer'):
            raise ContractError('reviewer_required','reviewer')
        return self.require('commands').enqueue('analyze',{'seed_id':seed_id, **body},phase='analyze')

    def review_blueprint(self, blueprint_id, body):
        if not body.get('reviewer'):
            raise ContractError('reviewer_required','reviewer')
        bp = self.require('blueprints').accept(blueprint_id,body['content_hash'],body['reviewer'])
        return bp.to_dict()

    # --------------------------------------------- deep analysis gate
    def _analysis_binding_gate(self,seed_id,provenance,binding):
        from ..analysis.deep import bound_gate
        bound_gate(self.db,seed_id,(provenance or {}).get('artifact_sha256',''),binding)

    def _experiment_blueprint(self,exp):
        bp=next((x for x in self.collection('blueprints') if x['content_hash']==exp.blueprint_hash),None)
        if not bp: raise ContractError('blueprint_missing','experiment')
        return bp

    def verify_run_gate(self,plan_id):
        row=self.db.conn.execute("SELECT body FROM records WHERE kind='productionplan' AND id=?",(plan_id,)).fetchone()
        if not row: raise ContractError('no_quote','plan_id')
        plan=json.loads(row[0])
        exp=self.require('experiments')._latest(plan['experiment_id'])
        bp=self._experiment_blueprint(exp)
        self._analysis_binding_gate(bp['seed_id'],bp.get('provenance'),bp.get('analysis'))

    def start_analysis(self,seed_id,body):
        a=self.require('ref_analysis').start(seed_id,body.get('reviewer',''))
        self.require('commands').enqueue('analysis_evidence',{'seed_id':seed_id},phase='analyze')
        return a.to_dict()

    def analysis_for(self,seed_id):
        try: return self.require('ref_analysis').get(seed_id).to_dict()
        except ContractError as e:
            if e.code=='unknown_analysis': return None
            raise

    def save_analysis_section(self,seed_id,section,body,reviewer):
        svc=self.require('ref_analysis')
        if section=='understanding': return svc.save_understanding(seed_id,body,reviewer).to_dict()
        if section=='timeline': return svc.save_timeline(seed_id,body.get('sections',body),reviewer).to_dict()
        if section=='treatment': return svc.save_treatment(seed_id,body,reviewer).to_dict()
        raise ContractError('unknown_section','section',section)

    def import_analysis_transcript(self,seed_id,body):
        return self.require('ref_analysis').import_transcript(seed_id,body,body.get('reviewer','')).to_dict()

    def declare_analysis(self,seed_id,body):
        return self.require('ref_analysis').declare(seed_id,body.get('status',''),body.get('note',''),body.get('reviewer','')).to_dict()

    def rerun_analysis_stages(self,seed_id,body):
        svc=self.require('ref_analysis'); svc.get(seed_id)
        if body.get('rebuild_evidence'): svc.invalidate_evidence(seed_id)
        return self.require('commands').enqueue('analysis_evidence',{'seed_id':seed_id},phase='analyze')

    def review_analysis(self,seed_id,body):
        if not body.get('reviewer'): raise ContractError('reviewer_required','reviewer')
        return self.require('ref_analysis').review(seed_id,body['reviewer'],body.get('verdict','accept'),body.get('notes','')).to_dict()

    def author_template(self, body):
        bp = self.require('analysis').get(body['blueprint_id'])
        if bp.status != 'accepted':
            raise ContractError('blueprint_not_accepted','blueprint_id')
        self._analysis_binding_gate(bp.seed_id,bp.provenance,bp.analysis)
        return self.require('templates').author(bp,body.get('id') or 'tpl-'+uuid.uuid4().hex).to_dict()

    def _current(self, eid, expected=None, required=False):
        exp = self.require('experiments')._latest(eid)
        if required and expected is None:
            raise ContractError('expected_revision_required','revision')
        if expected is not None and expected != exp.revision:
            raise ContractError('stale_revision','revision',f'current {exp.revision}')
        return exp

    def create_experiment_draft(self, experiment_id, body):
        required = {'blueprint_id','template_id','segments','variants'}
        if not required <= body.keys():
            raise ContractError('incomplete_experiment','input',','.join(sorted(required-body.keys())))
        bp = self.require('analysis').get(body['blueprint_id'])
        template = self.require('templates').get(body['template_id'])
        if template.derived_from_blueprint != bp.content_hash:
            raise ContractError('template_blueprint_mismatch','template_id')
        self._analysis_binding_gate(bp.seed_id,bp.provenance,bp.analysis)
        products = [ProductSnapshot(**self.detail('productsnapshot', pid)) for pid in body.get('product_ids',[])]
        self._validate_segments(body['segments'],bp.target_frames)
        branches = body['variants']
        if {v.get('key') for v in branches} != {'B','C','D'} or len(branches)!=3:
            raise ContractError('four_variants_required','variants','A is implicit; supply B, C and D')
        with self.db.uow():
            self.require('experiments').create(experiment_id,bp.seed_id,bp,template,products,body['segments'],
                voice=body.get('voice'),music=body.get('music'), provider_policy=ProviderPolicy(**body.get('provider_policy',{})))
            for branch in branches:
                self._branch(experiment_id,branch)
        return self.experiment_results(experiment_id)

    def _branch(self,eid,branch):
        segments = branch['segments']
        self._validate_segments(segments,self._current(eid).packaging['target_frames'])
        return self.experiments.branch(eid,branch['key'],branch['factor'],branch['regions'],
            lambda b:{**b,'segments':copy.deepcopy(segments)},branch['hypothesis'],branch['primary_metric'],
            branch['allowed_fields'],branch.get('dependent_fields',[]))

    def _validate_segments(self,segments,total):
        from ..domain.clocks import FrameInterval, check_partition
        from ..api.inputs import SegmentInput
        from pydantic import ValidationError
        if not isinstance(segments,list):raise ContractError('invalid_segments','segments')
        try:
            for item in segments:SegmentInput.model_validate(item)
        except ValidationError:raise ContractError('invalid_segments','segments') from None
        intervals=[]
        if not segments or len({s['id'] for s in segments})!=len(segments):
            raise ContractError('invalid_segments','segments')
        for segment in segments:
            target=segment['target']; intervals.append(FrameInterval(target['start_frame'],target['end_frame']))
            for field in ('picture','speech'):
                aid=(segment.get(field) or {}).get('artifact_id')
                if aid: self.artifacts.verified_path(aid)
        if check_partition(intervals,total):
            raise ContractError('invalid_partition','segments')

    def patch_experiment_draft(self,eid,patch,expected_revision):
        self._current(eid,expected_revision,True)
        if set(patch)-{'segments','variants','reason','voice','music'}:
            raise ContractError('reserved_field','patch')
        def edit(body):
            for field in ('segments','voice','music'):
                if field in patch:
                    body[field]=copy.deepcopy(patch[field]); body['packaging'][field]=copy.deepcopy(patch[field])
            self._validate_segments(body['segments'],body['packaging']['target_frames'])
            return body
        with self.db.uow():
            result=self.experiments.revise_control(eid,edit,patch.get('reason','operator edit'))
            for branch in patch.get('variants',[]): self._branch(eid,branch)
        return {'id':eid,'revision':result['revision'].revision,'status':'draft'}

    def quote_experiment(self,eid,expected_revision=None):
        exp=self._current(eid,expected_revision,True)
        bp=self._experiment_blueprint(exp)
        self._analysis_binding_gate(bp['seed_id'],bp.get('provenance'),bp.get('analysis'))
        for key in 'ABCD':
            if self.experiments._variant(eid,key).stale_reason:
                raise ContractError('stale_variant','variant',key)
        return self.require('commands').enqueue('quote',{'experiment_id':eid,'revision':exp.revision},
            experiment_id=eid,revision=exp.revision,identity=f'quote-{eid}-r{exp.revision}')

    def plan_for(self,eid):
        exp=self._current(eid)
        row=self.db.conn.execute("SELECT body FROM records WHERE kind='productionplan' AND json_extract(body,'$.experiment_id')=? AND json_extract(body,'$.experiment_revision')=? ORDER BY created_at DESC LIMIT 1",(eid,exp.revision)).fetchone()
        if not row: raise ContractError('no_quote','experiment_id',eid)
        return json.loads(row[0])

    def authorize_experiment(self,eid,expected_revision,body=None):
        body=body or {}; exp=self._current(eid,expected_revision,True); plan=self.plan_for(eid)
        if body.get('plan_hash') != plan['plan_hash'] or not body.get('reviewer'):
            raise ContractError('approval_binding_required','plan_hash/reviewer')
        bp=self._experiment_blueprint(exp)
        self._analysis_binding_gate(bp['seed_id'],bp.get('provenance'),bp.get('analysis'))
        # Product evidence is pinned to the packaged snapshot REVISION —
        # a post-approval refresh must never rewrite the approved facts.
        pins={p['snapshot_id']:p.get('revision') for p in exp.packaging.get('products',[])}
        snapshots=[]
        for pid in exp.product_snapshot_ids:
            rev=pins.get(pid)
            row=self.db.uow().records.get('productsnapshot',pid,revision=rev) if rev is not None else self.db.uow().records.get('productsnapshot',pid)
            if row is None:
                raise ContractError('pinned_revision_missing','productsnapshot',pid)
            snapshots.append(ProductSnapshot(**json.loads(row['body'])))
        report=self.experiments.acceptance_report(eid,self.analysis.get(bp['id']),self.templates.get(exp.packaging['template_ref']['id'],exp.packaging['template_ref']['revision']),snapshots)
        if report['problems']: raise ContractError('acceptance_blocked','experiment',json.dumps(report['problems']))
        with self.db.uow() as u:
            self.experiments.accept(eid,exp.content_hash)
            if plan['total_price']:
                auth=Authorization(schema_version='authorization.v1',id='auth-'+uuid.uuid4().hex,created_at=utcnow(),
                    status='authorized',scope_hash=plan['plan_hash'],caps=body.get('ceilings',{}),
                    allowed_providers=body.get('allowed_providers',[]),allowed_models=body.get('allowed_models',{}),
                    valid_until=body.get('valid_until',''),authorizing_action='operator '+body['reviewer'])
                self.production.authorize(plan['id'],auth,body.get('account',''),body.get('budget_ids',[]),auth.valid_until)
            approval={'plan_hash':plan['plan_hash'],'revision':exp.revision,'reviewer':body['reviewer']}
            u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",('local-run:'+plan['id'],json.dumps(approval)))
        return {'id':eid,'revision':exp.revision,'plan_hash':plan['plan_hash'],'status':'authorized'}

    def run_experiment(self,eid,expected_revision=None):
        exp=self._current(eid,expected_revision,True); plan=self.plan_for(eid)
        row=self.db.conn.execute("SELECT value FROM meta WHERE key=?",('local-run:'+plan['id'],)).fetchone()
        if not row or json.loads(row[0])['plan_hash']!=plan['plan_hash'] or exp.status!='accepted':
            raise ContractError('not_authorized','experiment_id')
        bp=self._experiment_blueprint(exp)
        self._analysis_binding_gate(bp['seed_id'],bp.get('provenance'),bp.get('analysis'))
        return self.require('commands').enqueue('run',{'plan_id':plan['id']},experiment_id=eid,
            revision=exp.revision,identity=f'run-{eid}-r{exp.revision}')

    def pause_experiment(self,eid):
        self._current(eid); self.require('scheduler').pause(eid)
        return {'id':eid,'paused':True}

    def resume_experiment(self,eid):
        self._current(eid); self.require('scheduler').resume(eid)
        return {'id':eid,'resumed':True}

    def reconcile_job(self,jid):
        self.require('commands').get(jid)
        return self.commands.enqueue('reconcile',{'job_id':jid},phase='collect')

    def _final(self,variant_id):
        variant=self.detail('variantplan',variant_id)
        self._current(variant['experiment_id'],variant['experiment_revision'])
        row=self.db.conn.execute("SELECT value FROM meta WHERE key=?",('final:'+variant_id,)).fetchone()
        if not row: raise ContractError('final_not_ready','variant_id')
        final=json.loads(row[0]); path=self.artifacts.verified_path(final['artifact_id'])
        binding=self.require('quality').binding(path,final['composition_id'],final['artifact_id'])
        return variant,final,path,binding

    def record_review(self,variant_id,check_type,verdict,target_hash,reviewer='',evidence_ids=(),now='', notes=''):
        if not reviewer: raise ContractError('reviewer_required','reviewer')
        if check_type!='creative': raise ContractError('automated_check_required','check_type')
        variant,final,path,binding=self._final(variant_id)
        if binding['artifact_sha256']!=target_hash: raise ContractError('stale_revision','target_hash')
        return self.quality.record_verdict('review-'+uuid.uuid4().hex,target_hash,check_type,verdict,
            evidence=evidence_ids,now=now,binding=binding,reviewer=reviewer,limitations=[notes] if notes else [])

    def review_assets(self,eid,body,expected_revision):
        self._current(eid,expected_revision,True); plan=self.plan_for(eid)
        if not body.get('reviewer') or body.get('plan_hash')!=plan['plan_hash']:
            raise ContractError('approval_binding_required','plan_hash/reviewer')
        accepted=[]
        for aid in body.get('artifact_ids',[]):
            self.artifacts.verified_path(aid); art=self.db.uow().artifacts.get(aid)
            self.quality.record_verdict('asset-review-'+uuid.uuid4().hex,art['sha256'],'asset',body['verdict'],
                 binding={'plan_hash':plan['plan_hash'],'artifact_id':aid},reviewer=body['reviewer'])
            accepted.append(aid)
        with self.db.uow() as u:
            u.conn.execute("UPDATE jobs SET status='ready',lease_owner=NULL,lease_expires=NULL WHERE experiment_id=? AND revision=? AND phase='review' AND status='awaiting_review'",(eid,expected_revision))
        return {'reviewed':accepted}

    def create_variant_revision(self,variant_id,reason,patch):
        raise ContractError('revise_experiment_required','variant_id','Edit the experiment with its current expected revision and rebranch treatments')

    def deliver_variant(self,variant_id,body,expected_revision):
        variant,final,path,binding=self._final(variant_id)
        self._current(variant['experiment_id'],expected_revision,True)
        if set(body)-{'folder_id','reviewer','valid_until','account','check_ids','artifact_id','target_hash'}:
            raise ContractError('reserved_field','delivery','Delivery accepts registered artifact identities only')
        if body.get('artifact_id')!=final['artifact_id'] or body.get('target_hash')!=binding['artifact_sha256']:
            raise ContractError('stale_revision','artifact_id/target_hash')
        if not body.get('reviewer') or not body.get('valid_until') or not body.get('account'):
            raise ContractError('approval_binding_required','delivery')
        folder=self.config.get('drive_folder_id')
        if not folder or body.get('folder_id')!=folder:
            raise ContractError('destination_not_authorized','folder_id')
        self.require('delivery'); accepted=self.quality.accept(path,body.get('check_ids',[]),binding)
        from ..delivery.service import delivery_name
        from ..execution.effects import EffectService
        name=delivery_name(variant['experiment_id'],variant['variant_key'],variant.get('changed_factor') or 'control',variant['experiment_revision'],variant['target_frames']/self._current(variant['experiment_id']).output_clock['num'])
        did='delivery-'+content_hash([binding,folder,name])[:24]
        existing=self.delivery._get(did)
        if existing and existing['status']=='verified':
            try: cleaned=json.loads(existing.get('cleanup_receipt','{}')).get('state')=='verified'
            except ValueError: cleaned=False
            if cleaned:return {'status':'verified','delivery_id':did,'link':existing['drive_link']}
            return self.commands.enqueue('cleanup',{'delivery_id':did,'variant_id':variant_id},phase='collect',identity='cleanup-'+did)
        prior=self.db.uow().records.get('appcommand',did)
        if prior:
            # A still-live job is already retrying; a dead or failed one
            # gets an explicit transfer retry under a fresh identity.
            job=self.db.uow().jobs.get(did)
            if job and job['status'] not in ('failed','succeeded'):
                return {'job_id':did,'accepted':True}
            if existing and existing['status']=='conflict':
                return {'status':'conflict','delivery_id':did,
                        'detail':'remote name exists with different content — resolve or rename before retry'}
            n=(existing or {}).get('retry_count') or 0
            if existing:
                return self.commands.enqueue('delivery_retry',
                    {'delivery_id':did,'variant_id':variant_id},
                    experiment_id=variant['experiment_id'],revision=expected_revision,
                    phase='deliver',identity=f'{did}:retry:{n}')
            saved=json.loads(prior['body'])
            return self.commands.enqueue('delivery',saved['input'],
                experiment_id=variant['experiment_id'],revision=expected_revision,
                phase='deliver',identity=f'{did}:retry:{n}')
        req={'artifact_sha256':binding['artifact_sha256'],'folder_id':folder,'name':name,
             'size':path.stat().st_size,'md5':hashlib.md5(path.read_bytes()).hexdigest()}
        command={'delivery_id':did,'variant_id':variant_id,'artifact_id':final['artifact_id'],
             'binding':binding,'check_ids':accepted['check_ids'],'folder_id':folder,'name':name}
        aid='auth-'+uuid.uuid4().hex
        auth=Authorization(schema_version='authorization.v1',id=aid,created_at=utcnow(),status='authorized',
             scope_hash=binding['composition_hash'],allowed_providers=['drive'],allowed_models={'drive':['files']},
             valid_until=body['valid_until'],authorizing_action='operator '+body['reviewer'])
        EffectService(self.db,self.executor).approve(auth,'composition',binding['composition_id'],[
             {'key':'delivery','kind':'delivery','provider':'drive','model':'files','account':body['account'],'request':req}],[])
        command['authorization_id']=aid
        return self.commands.enqueue('delivery',command,experiment_id=variant['experiment_id'],revision=expected_revision,
             phase='deliver',identity=did)

    def record_publication(self,variant_id,body,revision):
        return self.require('publication_work').plan(variant_id,body,revision)

    def experiment_results(self,eid):
        exp=self._current(eid); variants=[]
        for key in 'ABCD':
            try:
                v=self.experiments._variant(eid,key).to_dict()
                row=self.db.conn.execute("SELECT value FROM meta WHERE key=?",('final:'+v['id'],)).fetchone()
                if row: v['final']=json.loads(row[0])
                variants.append(v)
            except ContractError: pass
        return {'id':eid,'experiment_id':eid,'revision':exp.revision,'status':exp.status,
            'experiment':exp.to_dict(),'variants':variants,'results':[], 'coverage':'unavailable'}

    def media_path(self,asset_id):
        return self.require('artifacts').verified_path(asset_id)

    def events_since(self,stream,seq=0,limit=500):
        if stream=='factory':
            rows=self.db.conn.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?', (seq,limit)).fetchall()
            return [{**dict(r),'body':json.dumps(redact(json.loads(r['body'])))} for r in rows]
        return self.db.uow().events.since(stream,seq=seq)[:limit]
