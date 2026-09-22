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
    'metadatapackages':'metadatapackage','checkpoints':'checkpointschedule','selections':'seedselection','lineages':'roundlineage','loops':'looppolicy','autoruns':'autorun'}


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
                recheck = getattr(adapter, 'refresh_readiness', None)
                ready = recheck() if refresh and callable(recheck) else adapter.readiness()
            except Exception as error:
                ready = {"error":type(error).__name__}
            out[name] = {k: ready.get(k) is True for k in ('installed','authenticated','catalog_visible','contract_tested','live_qualified')}
            out[name]['tested'] = out[name]['contract_tested']
            out[name]['qualified'] = out[name]['live_qualified']
            out[name]['detail'] = redact(ready)
        self._readiness_cache=out;self._readiness_at=time.monotonic()
        return out

    def collection(self, name):
        if name == 'autoruns':
            return self.autorun.list()
        if name=='budgets':
            from ..budget import BudgetService
            ledger=BudgetService(self.db)
            totals = {r['id']: r for r in ledger.spend_breakdown()}
            return [{**dict(r),**totals[r['id']],**ledger.selection_info(r['id']),'available':ledger.available(r['id'])} for r in self.db.conn.execute('SELECT * FROM budgets')]
        if name == 'reservations':
            return self.reservations()
        if name == 'queue':
            from .history import DashboardHistory
            return {**self.require('scheduler').status_snapshot(),
                    'history': DashboardHistory(self.db).snapshot()}
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

    def reservations(self, status=None):
        """Every hold with the attempt it funds, so an operator can see where
        spend authority went and settle or release it on evidence. A hold
        without a linked attempt is shown as such; nothing is inferred."""
        rows=self.db.conn.execute(
            "SELECT r.id,r.authorization_id,r.request_hash,r.status,r.created_at,r.settled_at,r.evidence,"
            " a.id AS attempt_id,a.job_id,a.status AS attempt_status,json_extract(a.body,'$.provider') AS provider,"
            " json_extract(a.body,'$.model') AS model"
            " FROM reservations r LEFT JOIN attempts a ON json_extract(a.body,'$.reservation_id')=r.id"
            + (" WHERE r.status=?" if status else "") + " ORDER BY r.created_at DESC",
            (status,) if status else ()).fetchall()
        out=[]
        for r in rows:
            lines=[dict(l) for l in self.db.conn.execute(
                "SELECT budget_id,amount,settled_amount,kind FROM reservation_lines WHERE reservation_id=?",(r['id'],))]
            out.append({**dict(r),'lines':lines})
        return out

    def settle_reservation(self, reservation_id, body):
        """Operator settlement of a hold with evidence (invoice, provider
        usage page). Amounts default to the reserved amounts; the ledger
        records a variance when an actual exceeds its hold."""
        from ..budget import BudgetService
        if not body.get('reviewer') or not body.get('evidence'):
            raise ContractError('evidence_required','reviewer/evidence')
        kind=body.get('kind') or 'invoice_confirmed'
        if kind=='reported_usage':
            raise ContractError('bad_settlement_kind','kind','reported_usage is provider-declared only')
        lines={l['budget_id']:l['amount'] for l in self.db.conn.execute(
            "SELECT budget_id,amount FROM reservation_lines WHERE reservation_id=?",(reservation_id,))}
        if not lines:
            raise ContractError('unknown_reservation','id',reservation_id)
        amounts=dict(lines)
        if 'amount' in body:
            if type(body['amount']) is not int or body['amount']<0:
                raise ContractError('invalid_amount','amount',repr(body.get('amount')))
            amounts={b:body['amount'] for b in lines}
        for b,v in (body.get('amounts') or {}).items():
            if b not in lines or type(v) is not int or v<0:
                raise ContractError('invalid_amount',b,repr(v))
            amounts[b]=v
        evidence=f"{kind} by {body['reviewer']}: {body['evidence']}"
        BudgetService(self.db).settle(reservation_id,kind,amounts,evidence)
        with self.db.uow() as u:
            u.events.append('factory','reservation_settled_by_operator',
                            {'reservation_id':reservation_id,'kind':kind,'amounts':amounts,'reviewer':body['reviewer']})
        return {'reservation_id':reservation_id,'status':'settled','amounts':amounts}

    def reconcile_invalid_analysis(self, attempt_id, body):
        from ..autorun.recovery import AnalysisRecovery
        return AnalysisRecovery(self).settle_unusable(attempt_id, body)

    def release_reservation(self, reservation_id, body):
        """Free a hold only when its attempt verifiably never charged: no
        attempt, a cancelled/prepared attempt, or a failed one backed by
        the operator's provider-side evidence. A downloaded or succeeded
        attempt was charged and must be settled, never released."""
        from ..budget import BudgetService
        if not body.get('reviewer') or not body.get('evidence'):
            raise ContractError('evidence_required','reviewer/evidence')
        att=self.db.conn.execute(
            "SELECT id,status FROM attempts WHERE json_extract(body,'$.reservation_id')=?",(reservation_id,)).fetchall()
        blocking=[a for a in att if a['status'] not in ('failed','cancelled','prepared')]
        if blocking:
            raise ContractError('release_refused','attempt_id',
                                f"{blocking[0]['id']} is {blocking[0]['status']}: charged or unresolved — settle with evidence instead")
        evidence=f"released by {body['reviewer']}: {body['evidence']}"
        BudgetService(self.db).release(reservation_id,evidence)
        with self.db.uow() as u:
            u.events.append('factory','reservation_released_by_operator',
                            {'reservation_id':reservation_id,'reviewer':body['reviewer'],'attempts':[a['id'] for a in att]})
        return {'reservation_id':reservation_id,'status':'released'}

    def adjust_reservation(self, reservation_id, body):
        """Upgrade a settled reservation to a more-confirmed kind —
        usage_estimate → reported_usage → invoice_confirmed — with the
        original entry preserved in the event log."""
        from ..budget import BudgetService
        if not body.get('reviewer') or not body.get('evidence'):
            raise ContractError('evidence_required','reviewer/evidence')
        kind=body.get('kind') or 'invoice_confirmed'
        saved={l['budget_id']:l for l in self.db.conn.execute(
            "SELECT budget_id,amount,settled_amount FROM reservation_lines "
            "WHERE reservation_id=?",(reservation_id,))}
        if not saved:
            raise ContractError('unknown_reservation','id',reservation_id)
        amounts={b:l['settled_amount'] for b,l in saved.items()}
        for b,v in (body.get('amounts') or {}).items():
            if b not in saved or type(v) is not int or v<0:
                raise ContractError('invalid_amount',b,repr(v))
            amounts[b]=v
        evidence=(f"{kind} by {body['reviewer']}: {body['evidence']}")
        BudgetService(self.db).adjust_settlement(
            reservation_id,kind,amounts,evidence,operator=body['reviewer'])
        return {'reservation_id':reservation_id,'status':'settled',
                'kind':kind,'amounts':amounts}

    def resolve_overrun(self, body):
        """Lift the dispatch block after a spend overrun — the overrun
        event stays in the ledger; the resolution is recorded."""
        from ..budget import BudgetService
        prior=BudgetService(self.db).resolve_overrun(
            body.get('reviewer',''),body.get('evidence',''),
            body.get('resolution',''))
        return {'reservation_id':prior.get('reservation'),
                'resolved':True,'overrun':prior}

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

    def attach_media(self, seed_id, artifact_id, role="master"):
        self.require('artifacts').verified_path(artifact_id)
        return self.require('seeds').attach_media(
            seed_id, artifact_id, role=role)[0].to_dict()

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
        bp = self.require('blueprints').accept(
            blueprint_id, body['content_hash'], body['reviewer'],
            allow_flags=bool(body.get('allow_flags', False)),
            notes=body.get('notes', ''))
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
        self._enqueue_analysis(seed_id)
        return a.to_dict()

    def _enqueue_analysis(self, seed_id):
        snapshot = self.analysis_for(seed_id)
        request = {'seed_id': seed_id, 'edit_token': snapshot['edit_token'],
                   'analysis_revision': snapshot['revision'], 'source_sha256': snapshot['source_sha256']}
        return self.require('commands').enqueue('analysis_evidence', request, phase='analyze',
            identity='analysis-evidence-' + content_hash(request)[:32])

    def analysis_for(self,seed_id):
        try:
            with self.db.uow():
                a = self.require('ref_analysis').get(seed_id)
                from ..analysis.deep import edit_token
                return {**a.to_dict(), 'edit_token': edit_token(a)}
        except ContractError as e:
            if e.code=='unknown_analysis': return None
            raise

    def _analysis_edit(self, seed_id, body, action, *, queued=False):
        # Keep validation and mutation in one transaction, including direct
        # service callers. Revision alone misses edits within one revision.
        with self.db.uow():
            snapshot = self.analysis_for(seed_id)
            if not body.get('edit_token'):
                raise ContractError('analysis_edit_token_required', 'edit_token',
                                    'Reload this source before saving.')
            if not snapshot or body['edit_token'] != snapshot['edit_token']:
                raise ContractError('stale_revision', 'edit_token',
                                    'This source changed. Reload before saving.')
            result = action()
            return result if queued else self.analysis_for(seed_id)

    def save_analysis_section(self,seed_id,section,body,reviewer):
        svc=self.require('ref_analysis')
        if section=='understanding': return self._analysis_edit(seed_id,body,lambda:svc.save_understanding(seed_id,body,reviewer))
        if section=='timeline': return self._analysis_edit(seed_id,body,lambda:svc.save_timeline(seed_id,body.get('sections',body),reviewer))
        if section=='treatment': return self._analysis_edit(seed_id,body,lambda:svc.save_treatment(seed_id,body,reviewer))
        raise ContractError('unknown_section','section',section)

    def import_analysis_transcript(self,seed_id,body):
        return self._analysis_edit(seed_id,body,lambda:self.require('ref_analysis').import_transcript(seed_id,body,body.get('reviewer','')))

    def declare_analysis(self,seed_id,body):
        return self._analysis_edit(seed_id,body,lambda:self.require('ref_analysis').declare(seed_id,body.get('status',''),body.get('note',''),body.get('reviewer','')))

    def rerun_analysis_stages(self,seed_id,body):
        def enqueue():
            svc=self.require('ref_analysis')
            if body.get('rebuild_evidence'): svc.invalidate_evidence(seed_id)
            return self._enqueue_analysis(seed_id)
        return self._analysis_edit(seed_id,body,enqueue,queued=True)

    def review_analysis(self,seed_id,body):
        if not body.get('reviewer'): raise ContractError('reviewer_required','reviewer')
        return self._analysis_edit(seed_id,body,lambda:self.require('ref_analysis').review(seed_id,body['reviewer'],body.get('verdict','accept'),body.get('notes','')))

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
                voice=body.get('voice'),music=body.get('music'), provider_policy=ProviderPolicy(**body.get('provider_policy',{})),
                output_profile=body.get('output_profile'), run_policies=body.get('run_policies'),
                source_timing=body.get('source_timing'), workflow=body.get('workflow'),
                creative_context=body.get('creative_context'), flashcut_policy=body.get('flashcut_policy'),
                flashcut_editorial=body.get('flashcut_editorial'))
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
        body = {'experiment_id':eid,'revision':exp.revision}
        if exp.packaging.get('workflow', {}).get('reference_policy') == 'first_clip.v1':
            runs = self.db.conn.execute("SELECT body FROM records WHERE kind='autorun' AND json_extract(body,'$.experiment_id')=? AND json_extract(body,'$.state.experiment_revision')=?", (eid, exp.revision)).fetchall()
            if len(runs) != 1:
                raise ContractError('reference_preparation_pending', 'quote', 'Wait for the automatic character-reference preparation to finish.')
            bindings = json.loads(runs[0]['body']).get('state', {}).get('reference_bindings', {})
            from ..creative.references import bound_request
            for key in 'ABCD':
                for segment in self.experiments._variant(eid, key).segments:
                    if key + ':' + segment['id'] not in bindings:
                        raise ContractError('reference_preparation_pending', 'quote', 'Character-conditioned clips are still being prepared.')
                    bound_request(self, exp, key, segment, segment['picture']['request'], bindings)
            body['reference_bindings'] = bindings
        return self.require('commands').enqueue('quote',body,
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
        self.require('delivery'); accepted=self.delivery_acceptance(variant,final,path,binding,body.get('check_ids',[]))
        from ..delivery.service import delivery_name
        from ..execution.effects import EffectService
        name=delivery_name(variant['experiment_id'],variant['variant_key'],variant.get('changed_factor') or 'control',variant['experiment_revision'],variant['target_frames']/self._current(variant['experiment_id']).output_clock['num'])
        did='delivery-'+content_hash([binding,folder,name])[:24]
        existing=self.delivery._get(did)
        if self._current(variant['experiment_id']).packaging.get('workflow', {}).get('version') == 2:
            account = getattr(self.delivery.drive, 'expected_account', '') or ('fixture-drive' if self.config.get('mode','offline') == 'offline' else '')
            if body['account'] != account:
                raise ContractError('delivery_account_changed', 'account', 'Reconnect the original authorized account before delivery recovery.')
            if existing:
                self.delivery._account_binding(existing)
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
            if self._current(variant['experiment_id']).packaging.get('workflow', {}).get('version') == 2:
                # A pre-upload failure need not increment transfer count.
                # Reuse a live recovery command; number terminal commands,
                # not uploads, when an operator explicitly requests recovery.
                retries = self.db.conn.execute('SELECT id,status FROM jobs WHERE id LIKE ?',
                                               (did + ':retry:%',)).fetchall()
                live = next((r for r in retries if r['status'] not in ('failed','blocked','succeeded','cancelled')), None)
                if live: return {'job_id':live['id'],'accepted':True}
                n = len(retries)
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
             valid_until=body['valid_until'],authorizing_action=('run delivery policy: ' if self._current(variant['experiment_id']).packaging.get('run_policies', {}).get('delivery') == 'after_qc' else 'operator ') + body['reviewer'])
        EffectService(self.db,self.executor).approve(auth,'composition',binding['composition_id'],[
             {'key':'delivery','kind':'delivery','provider':'drive','model':'files','account':body['account'],'request':req}],[])
        command['authorization_id']=aid
        return self.commands.enqueue('delivery',command,experiment_id=variant['experiment_id'],revision=expected_revision,
             phase='deliver',identity=did)

    def reconcile_external_delivery(self, variant_id, body, expected_revision):
        variant, final, path, binding = self._final(variant_id)
        exp = self._current(variant['experiment_id'], expected_revision, True)
        if exp.packaging.get('delivery_tracking') != 'verified_receipts.v1':
            raise ContractError('historical_delivery_unchanged', 'variant_id', 'Historical deliveries are outside this reconciliation rollout.')
        if body.get('artifact_id') != final['artifact_id'] or body.get('target_hash') != binding['artifact_sha256']:
            raise ContractError('stale_revision', 'artifact_id/target_hash')
        folder = self.config.get('drive_folder_id')
        account = getattr(self.delivery.drive, 'expected_account', '') or ('fixture-drive' if self.config.get('mode','offline') == 'offline' else '')
        if not folder or body.get('folder_id') != folder or not account or body.get('account') != account:
            raise ContractError('destination_not_authorized', 'folder_id/account')
        name, fid = body.get('name'), body.get('file_id')
        if not isinstance(name,str) or not name.strip() or '/' in name or not isinstance(fid,str) or not fid.strip():
            raise ContractError('remote_identity_required', 'name/file_id')
        self.external_delivery_acceptance(variant, final, path, binding)
        did = 'external-delivery-' + content_hash([binding, folder, name, fid])[:24]
        return self.commands.enqueue('delivery_reconcile', {'delivery_id':did, 'variant_id':variant_id,
            'binding':binding, 'folder_id':folder, 'name':name, 'file_id':fid, 'account':account},
            experiment_id=variant['experiment_id'],revision=exp.revision,phase='collect',identity=did)

    def external_delivery_acceptance(self, variant, final, path, binding):
        problems = self.final_problems(variant['variant_key'], final, final['plan_id'])
        if problems: raise ContractError('acceptance_blocked', 'checks', str(problems))
        checks = [r['id'] for r in self._final_checks(final)
            if r.get('binding') == binding and not r.get('invalidated_by') and r['check_type'] != 'creative']
        return self.quality.accept(path, checks, binding, automated_delivery=True)

    def delivery_acceptance(self, variant, final, path, binding, check_ids):
        exp = self._current(variant['experiment_id'], variant['experiment_revision'])
        automated = exp.packaging.get('run_policies', {}).get('delivery') == 'after_qc'
        if automated:
            problems = self.final_problems(variant['variant_key'], final, final['plan_id'])
            if problems:
                raise ContractError('acceptance_blocked', 'checks', str(problems))
        return self.quality.accept(path, check_ids, binding, automated_delivery=automated)

    def record_publication(self,variant_id,body,revision):
        return self.require('publication_work').plan(variant_id,body,revision)

    def experiment_results(self,eid):
        exp=self._current(eid); variants=[]
        try: plan=self.plan_for(eid)
        except ContractError: plan=None
        for key in 'ABCD':
            try:
                v=self.experiments._variant(eid,key).to_dict()
                row=self.db.conn.execute("SELECT value FROM meta WHERE key=?",('final:'+v['id'],)).fetchone()
                if row:
                    final=json.loads(row[0])
                    # Revision scope: a final belongs to the plan that
                    # rendered it. An older revision's output must never
                    # relabel itself as the current one.
                    if plan and final.get('plan_id')==plan['id']:
                        v['final']=final
                        v['checks']=self._final_checks(final)
                        problems=self.final_problems(key,final,plan['id'])
                        v['validation']={
                            'state':'validation_blocked' if any(
                                not sup for _,sup in problems)
                                else ('stale' if problems else
                                      'ready_for_review'),
                            'problems':[m for m,_ in problems]}
                    elif final.get('plan_id')!= (plan or {}).get('id'):
                        v['validation']={
                            'state':'stale',
                            'problems':['rendered under a superseded '
                                        'plan — not the current answer']}
                v['changes']=self._variant_changes(exp,v)
                variants.append(v)
            except ContractError: pass
        return {'id':eid,'experiment_id':eid,'revision':exp.revision,'status':exp.status,
            'experiment':exp.to_dict(),'variants':variants,'results':[], 'coverage':'unavailable'}

    def _final_checks(self,final):
        checks=[]
        for cid in final.get('check_ids') or []:
            row=self.db.uow().records.get('review',cid)
            if row: checks.append(json.loads(row['body']))
        for r in self.db.conn.execute(
            "SELECT body FROM records WHERE kind='review' AND "
            "json_extract(body,'$.check_type')='automated_visual' AND "
            "json_extract(body,'$.target_hash')=? "
            "ORDER BY created_at DESC",(final.get('sha256'),)).fetchall():
            checks.append(json.loads(r['body']))
        if final.get('composition_id') and final.get('artifact_id'):
            try:
                binding = self.quality.binding(self.artifacts.verified_path(final['artifact_id']),
                                               final['composition_id'], final['artifact_id'])
                return self.quality.authoritative_checks(checks, binding)
            except ContractError:
                pass  # final_problems reports stale/broken binding separately.
        return checks

    def final_problems(self, variant_key, final, plan_id):
        """Mandatory-check gate for one final: every recorded check must
        pass against the CURRENT bytes, composition and plan. Missing,
        stale, failed or unbound checks are actionable problems — a file
        existing is not validation. → [(message, superseded)] where
        superseded marks problems that disappear on a re-render under
        the current plan."""
        stale_codes=("stale_composition","stale_plan","stale_experiment",
                     "unbound_composition","unregistered_final")
        problems=[]
        key=variant_key
        if final.get('plan_id')!=plan_id:
            return [(f"{key}: final was rendered under superseded plan "
                     f"{final.get('plan_id')}",True)]
        try:
            path=self.artifacts.verified_path(final['artifact_id'])
            binding=self.quality.binding(path,final['composition_id'],
                                         final['artifact_id'])
        except ContractError as e:
            return [(f"{key}: {e.code}",e.code in stale_codes)]
        ids=final.get('check_ids') or []
        if not ids:
            problems.append((f"{key}: no QC checks recorded",False))
            return problems
        kinds=set()
        for cid in ids:
            rec=self.quality._get(cid)
            if rec is None:
                problems.append((f"{key}: check {cid} missing",False))
                continue
            kinds.add(rec['check_type'])
            if rec.get('invalidated_by') or \
                    rec['target_hash']!=binding['artifact_sha256']:
                problems.append((f"{key}: {rec['check_type']} check {cid}"
                                 " is stale — it was recorded against "
                                 "different bytes",True))
                continue
            if rec.get('binding')!=binding:
                problems.append((f"{key}: check {cid} is bound to a "
                                 "different composition or plan",False))
                continue
            if rec['verdict']!='pass':
                detail='; '.join(rec.get('limitations') or []) \
                    or rec['verdict']
                problems.append((f"{key}: {rec['check_type']} check "
                                 f"{cid}: {rec['verdict']} — {detail}",
                                 False))
        if 'technical' not in kinds:
            problems.append((f"{key}: no technical check",False))
        if key!='A' and 'changed_region' not in kinds:
            problems.append((f"{key}: no unchanged-region comparison",
                             False))
        return problems

    def _variant_changes(self,exp,v):
        key=v.get('variant_key','')
        if key=='A':
            return {'summary':'Control — closest adaptation of the '
                    'reference structure and narration','factor':'control',
                    'regions':[],'changed_segments':[]}
        fps=exp.output_clock['num']/exp.output_clock['den']
        regions=[{'start_s':r['start_frame']/fps if 'start_frame' in r else r.get('start',0)/fps,
                  'end_s':r['end_frame']/fps if 'end_frame' in r else r.get('end',0)/fps}
                 for r in v.get('allowed_regions') or []]
        changed=[]
        try:
            a=self.experiments._variant(exp.experiment_id,'A')
            a_segs={s['id']:s for s in a.segments}
            for seg in v.get('segments') or []:
                old=a_segs.get(seg['id'])
                if old is None: continue
                diffs=[]
                if seg.get('copy')!=old.get('copy'): diffs.append('copy')
                if (seg.get('picture') or {})!=(old.get('picture') or {}): diffs.append('picture')
                if diffs: changed.append({'segment':seg['id'],'fields':diffs,
                                          'a_copy':old.get('copy',''),'b_copy':seg.get('copy','')})
        except ContractError: pass
        factor=v.get('changed_factor') or ''
        labels={'hook':'stronger opening hook','body':'clearer body section',
                'ending':'stronger payoff and loop'}
        full_video = exp.packaging.get('run_policies', {}).get('variation') == 'full_video'
        summary = v.get('hypothesis') or labels.get(factor,factor)
        if full_video:
            summary = 'Full-video multi-variable creative comparison — ' + summary
        return {'summary':summary,
                'factor':factor,'metric':v.get('primary_metric',''),
                'label':labels.get(factor,factor) + (' + full-video footage' if full_video else ''),
                'regions':regions,'changed_segments':changed}

    def media_path(self,asset_id):
        return self.require('artifacts').verified_path(asset_id)

    def media_info(self, asset_id):
        return self.require('artifacts').verified_media(asset_id)

    def events_since(self,stream,seq=0,limit=500):
        if stream=='factory':
            rows=self.db.conn.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?', (seq,limit)).fetchall()
            return [{**dict(r),'body':json.dumps(redact(json.loads(r['body'])))} for r in rows]
        return self.db.uow().events.since(stream,seq=seq)[:limit]
