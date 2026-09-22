"""Explicit supplementary quote after a proven request-format rejection.

The original envelopes/attempts remain immutable. This plan permits at most
two completed-response corrections and one shared missing-evidence request.
It cannot extend itself, and never converts unknown money into a refund.
"""
from copy import deepcopy
from fractions import Fraction
import json

from ..analysis.source_evidence import binding_from_db
from ..domain.errors import ContractError
from ..domain.records import content_hash
from ..execution.effects import wire_hash
from ..testing.fakes import ProviderError


class FlashcutFormatRecovery:
    def __init__(self,auto):
        self.auto,self.s=auto,auto.s

    def _rejection(self,run):
        found=[]
        for index,request in run.state.get('flashcut_structure_repairs',{}).items():
            for jid in run.state.get(f'flashcut_structure_{index}_jobs',[]):
                job=self.s.db.uow().jobs.get(jid)
                attempts=list(self.s.db.conn.execute('SELECT * FROM attempts WHERE job_id=?',(jid,)))
                if not job or job['status']!='failed' or len(attempts)!=1:continue
                attempt=attempts[0]
                if attempt['status']!='failed' or attempt['request_hash']!=wire_hash(request) or attempt['remote_id']:continue
                for event in self.s.db.uow().events.since('attempt:'+attempt['id']):
                    body=json.loads(event['body'])
                    if event['type']=='submit_failed' and body.get('http_status')==400 and body.get('class')=='pre_acceptance':
                        found.append({'job_id':jid,'attempt_id':attempt['id'],'request_hash':attempt['request_hash'],
                                      'event_seq':event['seq'],'diagnostic_sha256':content_hash(body)})
        if not found:raise ContractError('flashcut_format_recovery_unproven','rejection')
        return found

    def quote(self,run):
        if run.state.get('flashcut_format_recovery'):
            return self.s.source_evidence.blobs.read(run.state['flashcut_format_recovery'])
        if run.status!='paused' or run.stage!='video_analysis' or not run.state.get('flashcut_response_recovery'):
            raise ContractError('flashcut_format_recovery_unavailable','run')
        adapter=self.s.providers['audiovisual_analysis_flashcut']
        evidence=self.s.source_evidence.get(run.state['source_evidence_id'])
        if binding_from_db(self.s.db,run.id)!=evidence['binding']:
            raise ContractError('source_evidence_stale','binding')
        original=self.s.source_evidence.blobs.read(evidence['analysis_plan'])
        prior=self.s.source_evidence.blobs.read(run.state['flashcut_response_recovery'])
        if prior['original_plan_identity']!=original['identity'] or prior['binding']!=original['binding']:
            raise ContractError('flashcut_recovery_mismatch','plan')
        entries,requests=[],[]
        for entry in prior['entries']:
            saved=deepcopy(entry)
            if entry['mode']=='replacement':
                jid=run.state['flashcut_response_repair_jobs'][entry['replacement_index']]
                request=prior['requests'][entry['replacement_index']]
                job=self.s.db.uow().jobs.get(jid)
                if job and job['status']=='succeeded':saved.update(mode='existing',job_id=jid)
                elif job and job['status']=='failed':
                    attempts=list(self.s.db.conn.execute('SELECT * FROM attempts WHERE job_id=?',(jid,)))
                    unfinished=[a for a in attempts if a['status'] not in ('failed','cancelled','succeeded')]
                    if len(unfinished)!=1 or unfinished[0]['status']!='unknown' or unfinished[0]['remote_id'] or unfinished[0]['request_hash']!=wire_hash(request):
                        raise ContractError('flashcut_response_unproven','format_recovery')
                    saved.update(mode='correction',request_index=len(requests),job_id=jid)
                    requests.append(adapter.format_recovery_request(request,unfinished[0]['id']))
                else:raise ContractError('flashcut_recovery_not_idle','job',jid)
            entries.append(saved)
        if not 1<=len(requests)<=2:raise ContractError('flashcut_recovery_exhausted','corrections')
        clarification=deepcopy(original['requests'][0])
        clarification.update(scope='clarification',prompt_version='flashcut_understanding.v2',response_contract='flashcut_compact.v2')
        clarification['context']['clarify_ids']=[c['id'] for c in clarification['context']['candidates']]+['source']
        clarification['context']['clarification_instruction']='Resolve every supplied candidate against the complete source. Report grounded observations and explicitly retain any unresolved candidate ID in essential_missing.'
        requests.append(clarification)
        usages=[adapter.prepared(r)[1] for r in requests]
        quotes=[adapter.price(r) for r in requests]
        reserve=sum(q['reserve_amount'] for q in quotes)
        gap=self.auto._cover(run,{'usd_micros':reserve},providers=(adapter.name,))
        if gap:raise ContractError('budget_exhausted','format_recovery',gap)
        cumulative=deepcopy(prior['cumulative_envelope'])
        cumulative['max_requests']+=len(requests)
        for field,limit in [('images','max_images'),('windows','max_windows'),('payload_bytes','max_payload_bytes'),
                            ('input_tokens_bound','max_input_tokens'),('output_tokens_bound','max_output_tokens')]:
            cumulative[limit]+=sum(u[field] for u in usages)
        cumulative['max_media_seconds']=str(Fraction(cumulative['max_media_seconds'])+sum((Fraction(u['media_seconds']) for u in usages),Fraction(0)))
        cumulative['reserve_usd_micros']+=reserve
        plan={'version':'flashcut_format_recovery.v1','run_id':run.id,'binding':original['binding'],
              'original_plan_identity':original['identity'],'prior_plan':run.state['flashcut_response_recovery'],
              'rejection':self._rejection(run),'entries':entries,'requests':requests,'quotes':quotes,'usage_bounds':usages,
              'max_requests':len(requests),'max_corrections':len(requests)-1,'max_shared_clarifications':1,
              'reserve_usd_micros':reserve,'cumulative_envelope':cumulative}
        plan['identity']=content_hash(plan)
        return plan

    def enable(self,run,identity,reviewer):
        if not isinstance(reviewer,str) or not reviewer.strip():raise ContractError('reviewer_required','reviewer')
        plan=self.quote(run)
        if identity!=plan['identity']:raise ContractError('flashcut_recovery_quote_changed','identity')
        if run.state.get('flashcut_format_recovery'):return
        run.state['flashcut_format_recovery']=self.s.source_evidence.blobs.put(plan)
        run.notes.append('Approved supplementary format recovery; prior clarification counters and unknown holds retained.')
        self.s.db.uow().events.append('autorun:'+run.id,'flashcut_format_recovery_approved',{
            'quote_identity':identity,'reviewer':reviewer.strip(),'max_requests':plan['max_requests'],
            'reserve_usd_micros':plan['reserve_usd_micros']})

    def enable_context_reuse(self,run,body):
        """Explicit evidence-only continuation; no provider or accounting edits."""
        from ..analysis.context_coverage import POLICY
        if run.stage!='video_analysis' or not run.state.get('flashcut_format_recovery'):
            raise ContractError('flashcut_recovery_unavailable','context_reuse')
        reviewer=body.get('reviewer')
        if not isinstance(reviewer,str) or not reviewer.strip():raise ContractError('reviewer_required','reviewer')
        record=self.s.source_evidence.get(run.state['source_evidence_id'])
        if binding_from_db(self.s.db,run.id)!=record['binding']:raise ContractError('source_evidence_stale','binding')
        original=self.s.source_evidence.blobs.read(record['analysis_plan'])
        if body.get('analysis_plan_identity')!=original['identity']:raise ContractError('flashcut_recovery_mismatch','analysis_plan')
        media={m['id']:m for q in original['requests'] for m in q['media']}
        candidates={c['id']:c for q in original['requests'] for c in q['context']['candidates']}
        observations=body.get('visual_evidence',[])
        if not isinstance(observations,list) or len(observations)>8:raise ContractError('invalid_visual_evidence','observations')
        bound=[]
        for item in observations:
            candidate=candidates.get(item.get('candidate_id'),{})
            try:
                index=int(candidate['id'].split(':')[1]);expected=[f'frame:{i}' for i in (index-1,index,index+1)]
                if (candidate['kind']!='visual_change_candidate' or not candidate['id'].startswith('visual:')
                        or item.get('evidence_ids')!=expected or not isinstance(item.get('description'),str)
                        or not 1<=len(item['description'])<=2000):raise ValueError()
                frames=[media[i] for i in expected]
                for frame in frames:
                    if frame['kind']!='image':raise ValueError()
                    self.s.artifacts.verified_path(frame['artifact_id'])
                if not Fraction(frames[0]['source_time'])<=Fraction(candidate['source_time'])<=Fraction(frames[-1]['source_time']):raise ValueError()
            except (KeyError,ValueError,TypeError):raise ContractError('invalid_visual_evidence','candidate_frames') from None
            bound.append({**item,'frames':frames,'source_time':candidate['source_time']})
        if len({o['candidate_id'] for o in bound})!=len(bound):raise ContractError('invalid_visual_evidence','duplicate')
        evidence={'version':POLICY,'binding':original['binding'],'analysis_plan_identity':original['identity'],
                  'reviewer':reviewer.strip(),'reviewer_type':'assistant','observations':bound}
        ref=self.s.source_evidence.blobs.put(evidence)
        if run.state.get('flashcut_context_reuse') and run.state['flashcut_context_reuse']!=ref:
            raise ContractError('flashcut_recovery_mismatch','local_evidence_changed')
        run.state['flashcut_context_reuse']=ref
        run.notes.append('Evidence-only context recovery authorized; unknown clarification retained and never retried.')
        self.s.db.uow().events.append('autorun:'+run.id,'flashcut_context_reuse_enabled',{'evidence':ref,'new_requests':0})

    def _gap_result(self,run,request,jid,clarification):
        """Local format repair is provisional until the fixed clarification."""
        source=next((m for m in clarification['media'] if m['id']=='source'),{})
        # A clock-aligned overview keeps the original source hash in
        # source_sha256 while its file hash identifies the proxy bytes.
        source_identity=source.get('source_sha256') or source.get('sha256')
        if (clarification.get('scope')!='clarification' or clarification['binding']!=request['binding']
                or 'source' not in clarification['context'].get('clarify_ids',[])
                or source.get('kind')!='video' or source_identity!=request['binding']['source_sha256']
                or not isinstance(source.get('sha256'),str) or len(source['sha256'])!=64
                or Fraction(source.get('source_start','-1'))!=0
                or Fraction(source.get('source_end','-1'))!=Fraction(request['context']['source_duration'])):
            raise ContractError('flashcut_gap_clarification_unavailable','quoted_source')
        job=self.s.db.uow().jobs.get(jid)
        attempts=list(self.s.db.conn.execute('SELECT * FROM attempts WHERE job_id=?',(jid,)))
        unresolved=[a for a in attempts if a['status'] not in ('failed','cancelled','succeeded')]
        if (not job or job['status']!='failed' or len(unresolved)!=1 or unresolved[0]['status']!='unknown'
                or unresolved[0]['remote_id'] or unresolved[0]['request_hash']!=wire_hash(request)):
            raise ContractError('flashcut_response_unproven','coverage_gap')
        adapter=self.s.providers['audiovisual_analysis_flashcut']
        proof=adapter.inspect_saved_coverage_gaps(request,unresolved[0]['id'])
        evidence={'version':'coverage_gap_recovery.v1','job_id':jid,'proof':proof,
                  'required_clarification_hash':wire_hash(clarification)}
        saved=run.state.get('flashcut_gap_evidence',{}).get(jid)
        if saved:
            if self.s.source_evidence.blobs.read(saved)!=evidence:
                raise ContractError('flashcut_response_unproven','coverage_gap_changed')
        else:
            run.state.setdefault('flashcut_gap_evidence',{})[jid]=self.s.source_evidence.blobs.put(evidence)
            self.auto._put(run)
            self.s.db.uow().events.append('autorun:'+run.id,'flashcut_gap_clarification_required',{
                'job_id':jid,'evidence':run.state['flashcut_gap_evidence'][jid],
                'accounting':'unknown_retained','do_not_retry':True})
        return proof['result']

    @staticmethod
    def gaps_resolved(provisional,output):
        from ..analysis.flashcut_vertex import _covered_by_windows
        coverage=[{'source_start':str(o['start_s']),'source_end':str(o['end_s'])}
                  for o in output['observations'] if o['confidence']=='observed' and 'source' in o['evidence_ids']]
        return all(_covered_by_windows(Fraction(r['start_s']),Fraction(r['end_s']),coverage)
                   for value in provisional.values() for r in value['coverage_gap_recovery']['claimed_ranges'])

    def clarification_status(self,run):
        jobs=run.state['flashcut_format_clarify_jobs']
        outcome=self.auto._jobs(run,jobs,'flashcut_format_clarification_failed')
        if not isinstance(outcome,tuple) or outcome[0]!='pause':return outcome
        for jid in jobs:
            for attempt in self.s.db.conn.execute("SELECT id FROM attempts WHERE job_id=? AND status='unknown'",(jid,)):
                for event in self.s.db.uow().events.since('attempt:'+attempt['id']):
                    body=json.loads(event['body']);status=body.get('http_status')
                    if event['type']=='ack_lost' and type(status) is int and 500<=status<600:
                        return ('pause','flashcut_format_clarification_failed',
                            f'Google returned HTTP {status} during the final bounded clarification. No usable answer was returned; its outcome and cost remain uncertain.',
                            'Do not retry this unknown request. Preserve its estimate and inspect the saved evidence before planning further recovery. Resume alone cannot resolve this failure.')
        return outcome

    def collect(self,run,original):
        plan=self.s.source_evidence.blobs.read(run.state['flashcut_format_recovery'])
        if (plan['run_id']!=run.id or plan['binding']!=original['binding'] or plan['original_plan_identity']!=original['identity']
                or plan['identity']!=content_hash({k:v for k,v in plan.items() if k!='identity'}) or not 2<=len(plan['requests'])<=3
                or plan['rejection']!=self._rejection(run)):
            raise ContractError('flashcut_recovery_mismatch','format_plan')
        adapter=self.s.providers['audiovisual_analysis_flashcut']
        if [adapter.price(r) for r in plan['requests']]!=plan['quotes']:
            raise ContractError('flashcut_recovery_quote_changed','provider_price')
        for entry in plan['entries']:
            if entry['mode']=='saved':
                if adapter.inspect_saved_response(original['requests'][entry['index']],entry['proof']['attempt_id'])!=entry['proof']:
                    raise ContractError('flashcut_response_unproven','saved_response_changed')
            elif entry['mode']=='existing' and self.s.db.uow().jobs.get(entry['job_id'])['status']!='succeeded':
                raise ContractError('flashcut_response_unproven','existing_result')
        # Qualify the smaller overview before submitting the large window
        # request. A first-request rejection must not launch sibling work.
        correction_jobs=[]
        provisional={}
        for index,request in enumerate(plan['requests'][:-1]):
            tag=f'flashcut_format_{index}'
            outcome=self.auto._run_effect(run,'analysis',adapter.name,adapter.model,[request],tag)
            if outcome!='wait':return outcome,[]
            ids=run.state[tag+'_jobs']
            if len(ids)==1 and self.s.db.uow().jobs.get(ids[0])['status']=='failed':
                try:
                    provisional[ids[0]]=self._gap_result(run,request,ids[0],plan['requests'][-1])
                except (ContractError,ProviderError) as error:
                    return ('pause','flashcut_format_recovery_failed',
                        f'{getattr(error, "code", "correction_invalid")}: The completed correction did not pass evidence validation. Its saved answer and cost hold are preserved.',
                        'Inspect the bound response; this recovery cannot add requests, discard missing evidence or replay unknown submissions.'),[]
                correction_jobs.extend(ids)
                continue
            outcome=self.auto._jobs(run,ids,'flashcut_format_recovery_failed')
            if outcome!='next':return outcome,[]
            correction_jobs.extend(ids)
        outputs=[];requests=[]
        prior=self.s.source_evidence.blobs.read(plan['prior_plan'])
        for entry in plan['entries']:
            request=(plan['requests'][entry['request_index']] if entry['mode']=='correction' else
                     prior['requests'][entry['replacement_index']] if entry['mode']=='existing' and 'replacement_index' in entry else
                     original['requests'][entry['index']])
            if entry['mode']=='saved':
                proof=adapter.inspect_saved_response(original['requests'][entry['index']],entry['proof']['attempt_id'])
                if proof!=entry['proof']:raise ContractError('flashcut_response_unproven','saved_response_changed')
                output=proof['result']
            else:
                jid=correction_jobs[entry['request_index']] if entry['mode']=='correction' else entry['job_id']
                output=provisional[jid] if jid in provisional else self.s.commands.get(jid)['command']['result']['result']
            outputs.append(output)
            requests.append(request)
        pending={i for out in outputs for i in out['essential_missing']}
        if run.state.get('flashcut_context_reuse'):
            from ..analysis.context_coverage import resolve_context_coverage
            local=self.s.source_evidence.blobs.read(run.state['flashcut_context_reuse'])
            for observation in local['observations']:
                for frame in observation['frames']:self.s.artifacts.verified_path(frame['artifact_id'])
            resolution=resolve_context_coverage(requests,outputs,local_evidence=local)
            ref=self.s.source_evidence.blobs.put(resolution)
            if run.state.get('flashcut_context_resolution')!=ref:
                run.state['flashcut_context_resolution']=ref;self.auto._put(run)
            pending={p['flag'] for p in resolution['pending']}
            if not pending:
                # Keep local inspection distinct from Google responses.
                outputs.append({'scope':'local_evidence','binding':plan['binding'],'essential_missing':[],
                    'context_resolution':ref,'local_evidence':run.state['flashcut_context_reuse'],'observations':[
                        {'id':o['candidate_id'],'kind':'action','start_s':float(Fraction(o['frames'][0]['source_time'])),
                         'end_s':float(Fraction(o['frames'][-1]['source_time'])),'time_basis':'source',
                         'description':o['description'],'evidence_ids':o['evidence_ids'],
                         'role_ids':[],'text_role':'none','confidence':'observed'} for o in local['observations']]})
        if pending:
            request=plan['requests'][-1]
            if not pending.issubset(request['context']['clarify_ids']):
                return ('pause','flashcut_essential_evidence_unresolved',', '.join(sorted(pending)),
                    'Missing evidence is outside the frozen recovery request. Preserve all records and re-plan explicitly.'),[]
            outcome=self.auto._run_effect(run,'analysis',adapter.name,adapter.model,[request],'flashcut_format_clarify')
            if outcome!='wait':return outcome,[]
            outcome=self.clarification_status(run)
            if outcome!='next':return outcome,[]
            output=self.s.commands.get(run.state['flashcut_format_clarify_jobs'][0])['command']['result']['result']
            if output['essential_missing']:
                return ('pause','flashcut_essential_evidence_unresolved',', '.join(output['essential_missing']),
                    'The bounded format-recovery clarification is exhausted. No automatic repeat or counter reset is allowed.'),[]
            if not self.gaps_resolved(provisional,output):
                return ('pause','flashcut_essential_evidence_unresolved',
                    'The shared clarification did not provide observed source coverage for every reported gap.',
                    'The bounded clarification is exhausted. Preserve the gap evidence and quote any further work explicitly.'),[]
            if provisional:
                output={**output,'coverage_gap_resolution':{'version':'coverage_gap_resolution.v1',
                    'clarification_request_hash':wire_hash(request),
                    'evidence':[run.state['flashcut_gap_evidence'][jid] for jid in sorted(provisional)]}}
            outputs.append(output)
        if any(out.get('binding')!=plan['binding'] for out in outputs):raise ContractError('analysis_media_mismatch','format_recovery')
        return 'next',outputs
