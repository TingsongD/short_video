"""Explicit, bounded recovery of completed flash-cut responses.

Old jobs, receipts and reservations remain unchanged. A supplemental immutable
quote covers at most two distinct replacements; it never extends itself.
"""
from copy import deepcopy
from fractions import Fraction
import json

from ..domain.errors import ContractError
from ..execution.effects import wire_hash
from ..store.uow import utcnow
from ..testing.fakes import ProviderError


class FlashcutResponseRecovery:
    def __init__(self, auto):
        self.auto, self.s = auto, auto.s

    def release_completed_capacity(self, job_id, request):
        """A returned HTTP answer is not running remotely. Money stays unknown."""
        adapter=self.s.providers['audiovisual_analysis_flashcut']
        with self.s.db.uow() as u:
            job=u.jobs.get(job_id)
            attempts=list(u.conn.execute('SELECT * FROM attempts WHERE job_id=?',(job_id,)))
            unresolved=[a for a in attempts if a['status'] not in ('failed','cancelled','succeeded')]
            if (not job or job['status']!='failed' or len(unresolved)!=1
                    or unresolved[0]['status']!='unknown' or unresolved[0]['remote_id']
                    or unresolved[0]['request_hash']!=wire_hash(request)
                    or u.conn.execute('SELECT 1 FROM remote_holds WHERE job_id=?',(job_id,)).fetchone()):
                raise ContractError('flashcut_response_unproven','capacity')
            proof=adapter.inspect_saved_response(request,unresolved[0]['id'],validate=False)
            removed=u.conn.execute("DELETE FROM capacity_holds WHERE job_id=? AND capacity='dispatch' AND retained_reason='unfinished_remote_op'",(job_id,)).rowcount
            if removed:
                u.events.append('job:'+job_id,'completed_response_capacity_released',{
                    'proof':proof,'accounting':'unknown_retained','do_not_retry':True})
            return removed

    def enable(self, run, reviewer, *, automatic=False):
        if (not isinstance(reviewer, str) or not reviewer.strip()
                or run.stage != 'video_analysis' or run.params.get('profile_id') != 'flashcut_hypit.v1'):
            raise ContractError('flashcut_recovery_unavailable', 'run/reviewer')
        if run.state.get('flashcut_response_recovery'):
            return  # Durable fixed plan; Resume cannot reset its allowance.
        adapter = self.s.providers.get('audiovisual_analysis_flashcut')
        if not adapter or not callable(getattr(adapter, 'inspect_saved_response', None)):
            raise ContractError('flashcut_recovery_unavailable', 'provider')
        eid = run.state.get('source_evidence_id')
        record = self.s.source_evidence.get(eid)
        from ..analysis.source_evidence import binding_from_db
        if binding_from_db(self.s.db, run.id) != record['binding']:
            raise ContractError('source_evidence_stale', 'binding')
        original = self.s.source_evidence.blobs.read(record['analysis_plan'])
        jobs = run.state.get('flashcut_analysis_jobs', [])
        if not jobs or len(jobs) != len(original['requests']):
            raise ContractError('flashcut_recovery_unavailable', 'jobs')
        entries, replacements = [], []
        for index, (jid, request) in enumerate(zip(jobs, original['requests'])):
            job = self.s.db.uow().jobs.get(jid)
            if job and job['status'] == 'succeeded':
                entries.append({'job_id': jid, 'index': index, 'mode': 'existing'})
                continue
            if not job or job['status'] != 'failed':
                raise ContractError('flashcut_recovery_not_idle', 'job_id', jid)
            # Check the complete history. Never choose an arbitrary unresolved attempt.
            attempts = list(self.s.db.conn.execute('SELECT * FROM attempts WHERE job_id=?', (jid,)))
            unresolved = [a for a in attempts if a['status'] not in ('failed', 'cancelled', 'succeeded')]
            if (len(unresolved) != 1 or unresolved[0]['status'] != 'unknown'
                    or unresolved[0]['request_hash'] != wire_hash(request) or unresolved[0]['remote_id']):
                raise ContractError('flashcut_response_unproven', 'job_id', jid)
            try:
                proof = adapter.inspect_saved_response(request, unresolved[0]['id'])
            except ProviderError as error:
                raise ContractError('flashcut_saved_response_invalid', 'job_id',
                    jid + ': ' + error.code + '; no replacement submitted.') from None
            entry = {'job_id': jid, 'index': index, 'proof': proof}
            if proof['finish_reason'] == 'STOP':
                entry['mode'] = 'saved'
            else:
                entry.update(mode='replacement', replacement_index=len(replacements))
                replacements.append(adapter.replacement_request(request, unresolved[0]['id']))
            entries.append(entry)
        if len(replacements) > 2:
            raise ContractError('flashcut_recovery_exhausted', 'requests',
                                'More than two capped responses require a separately reviewed recovery plan.')
        usages = [adapter.prepared(r)[1] for r in replacements]
        quotes = [adapter.price(r) for r in replacements]
        reserve = sum(q['reserve_amount'] for q in quotes)
        gap = self.auto._cover(run, {'usd_micros': reserve}, providers=(adapter.name,)) if reserve else None
        if gap:
            raise ContractError('budget_exhausted', 'flashcut_recovery', gap)
        cumulative = deepcopy(original['envelope'])
        cumulative['max_requests'] += len(replacements)
        for field, maximum in [('images', 'max_images'), ('windows', 'max_windows'),
                               ('payload_bytes', 'max_payload_bytes'), ('input_tokens_bound', 'max_input_tokens'),
                               ('output_tokens_bound', 'max_output_tokens')]:
            cumulative[maximum] += sum(u[field] for u in usages)
        cumulative['max_media_seconds'] = str(Fraction(cumulative['max_media_seconds']) +
            sum((Fraction(u['media_seconds']) for u in usages), Fraction(0)))
        cumulative['reserve_usd_micros'] += reserve
        plan = {'version': 'flashcut_response_recovery.v1', 'run_id': run.id,
                'original_plan_identity': original['identity'], 'binding': original['binding'],
                'entries': entries, 'requests': replacements, 'quotes': quotes, 'usage_bounds': usages,
                'max_replacements': 2, 'supplemental_reserve_usd_micros': reserve,
                'cumulative_envelope': cumulative, 'reviewer': reviewer.strip(),
                'reviewer_type': 'automated' if automatic else 'human',
                'created_at': utcnow()}
        run.state['flashcut_response_recovery'] = self.s.source_evidence.blobs.put(plan)
        if automatic:
            run.notes.append('Automatic bounded response recovery planned within the saved run guardrail; old requests and cost holds retained, never replayed.')
        else:
            run.notes.append('Approved bounded response recovery; old requests and cost holds retained, never replayed.')
        self.s.db.uow().events.append('autorun:' + run.id,
            'flashcut_response_recovery_planned' if automatic else
            'flashcut_response_recovery_approved', {
            'plan': run.state['flashcut_response_recovery'],
            'reviewer': reviewer.strip(), 'reviewer_type': plan['reviewer_type'],
            'replacements': len(replacements),
            'supplemental_reserve_usd_micros': reserve})
        for entry in entries:
            if entry['mode']!='existing':
                self.release_completed_capacity(entry['job_id'],original['requests'][entry['index']])

    def collect(self, run, original):
        plan = self.s.source_evidence.blobs.read(run.state['flashcut_response_recovery'])
        if (plan['run_id'] != run.id or plan['original_plan_identity'] != original['identity']
                or plan['binding'] != original['binding'] or len(plan['requests']) > 2):
            raise ContractError('flashcut_recovery_mismatch', 'plan')
        adapter = self.s.providers['audiovisual_analysis_flashcut']
        for entry in plan['entries']:
            if entry['mode'] != 'existing':
                proof = adapter.inspect_saved_response(original['requests'][entry['index']], entry['proof']['attempt_id'])
                if proof != entry['proof']:
                    raise ContractError('flashcut_response_unproven', 'saved_response_changed')
                self.release_completed_capacity(entry['job_id'],original['requests'][entry['index']])
        if plan['requests']:
            outcome = self.auto._run_effect(run, 'analysis', adapter.name, adapter.model,
                                           plan['requests'], 'flashcut_response_repair')
            if outcome != 'wait':
                return outcome, []
        outputs = []
        for entry in plan['entries']:
            if entry['mode'] == 'saved':
                output = entry['proof']['result']
            else:
                jid = (entry['job_id'] if entry['mode'] == 'existing' else
                       run.state['flashcut_response_repair_jobs'][entry['replacement_index']])
                job=self.s.db.uow().jobs.get(jid)
                if entry['mode']=='replacement' and job['status']=='failed':
                    outcome,output=self._clarify_completed(run,jid,plan['requests'][entry['replacement_index']],entry['index'])
                    if outcome!='next':return outcome,[]
                else:
                    outcome=self.auto._jobs(run,[jid],'flashcut_response_repair_failed')
                    if outcome!='next':return outcome,[]
                    output = self.s.commands.get(jid)['command']['result']['result']
            outputs.append(output)
        return 'next', outputs

    def _clarify_completed(self,run,job_id,request,index):
        """Use the existing two-round clarification ledger, never a retry loop."""
        from ..analysis.analysis_envelope import AnalysisEnvelope
        adapter=self.s.providers['audiovisual_analysis_flashcut']
        try:
            self.release_completed_capacity(job_id,request)
            attempts=self.s.db.conn.execute("SELECT id FROM attempts WHERE job_id=? AND status='unknown'",(job_id,)).fetchall()
            clarification=adapter.structured_clarification(request,attempts[0]['id'])
            ledger=AnalysisEnvelope(self.s.source_evidence,adapter)
            ledger.claim(run.state['source_evidence_id'],clarification)
        except ContractError as error:
            return ('pause',error.code,error.detail or 'No proven complete response or clarification allowance remains.',
                    'Keep original operations and holds. No automatic resubmission; inspect the bound response and remaining envelope.'),None
        repairs=run.state.setdefault('flashcut_structure_repairs',{})
        if str(index) in repairs and repairs[str(index)]!=clarification:
            raise ContractError('flashcut_recovery_mismatch','clarification')
        if str(index) not in repairs:
            repairs[str(index)]=clarification
            self.auto._put(run)
        tag=f'flashcut_structure_{index}'
        outcome=self.auto._run_effect(run,'analysis',adapter.name,adapter.model,[clarification],tag)
        if outcome!='wait':return outcome,None
        outcome=self.auto._jobs(run,run.state[tag+'_jobs'],'flashcut_structure_clarification_failed')
        if outcome!='next':
            if isinstance(outcome,tuple) and outcome[0]=='pause':
                jid=run.state[tag+'_jobs'][0]
                attempts=self.s.db.conn.execute('SELECT id,status FROM attempts WHERE job_id=?',(jid,)).fetchall()
                for attempt in attempts:
                    if attempt['status']!='failed':continue
                    events=self.s.db.uow().events.since('attempt:'+attempt['id'])
                    rejected=any(e['type']=='submit_failed' and json.loads(e['body']).get('http_status')==400 for e in events)
                    if rejected:
                        outcome=('pause','flashcut_structure_clarification_failed',
                            'Google rejected the structured analysis request with HTTP 400 INVALID_ARGUMENT. No usable analysis was returned.',
                            'Qualify the provider request format and quote a revised bounded recovery plan before continuing. Do not replay unknown requests or reset clarification counters.')
                        break
            return outcome,None
        return 'next',self.s.commands.get(run.state[tag+'_jobs'][0])['command']['result']['result']
