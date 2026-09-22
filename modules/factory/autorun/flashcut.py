"""Future-profile orchestration, through existing jobs/effects only."""
from copy import deepcopy
from fractions import Fraction

from ..analysis.analysis_envelope import AnalysisEnvelope
from ..analysis.flashcut_requests import build_analysis_plan, jev_summaries, load_evidence
from ..domain.errors import ContractError
from ..domain.records import content_hash


class FlashcutAnalysis:
    def __init__(self,autorun):
        self.auto,self.s=autorun,autorun.s

    def status(self,run):
        result={'profile_id':'flashcut_hypit.v1','stage':run.state.get('flashcut_substage','waiting'),
                'jev_mode':'shadow','jev_status':run.state.get('jev_status','pending'),
                'clarifications_used':len(run.state.get('flashcut_clarifications',[])),
                'state':'complete' if run.state.get('flashcut_substage')=='complete' else
                        'paused' if run.status=='paused' else 'waiting' if run.state.get('provider_wait') else 'processing',
                **{k:v for k,v in run.state.get('provider_wait',{}).items() if k in ('reason','next_attempt_at')}}
        eid=run.state.get('source_evidence_id')
        if eid:
            record=self.s.source_evidence.get(eid)
            result['clarifications_used']=sum(r['clarification_round']>0 for r in record.get('analysis_requests',[]))
            result.update(record['progress'])
            if record['status']=='complete':result['stage']=run.state.get('flashcut_substage','understanding')
            result['repairs_used']=sum(max(0,c['attempts']-1) for c in self.s.source_evidence.chunks(eid))
            result['helper_recoveries_used']=max(0,record['executions']-1)
            result['evidence_status']=record['status']
        return result

    def advance(self,run):
        if run.state.get('analysis') is not None:
            self.auto._advance(run,'sections');return 'next'
        adapter=self.s.providers.get('audiovisual_analysis_flashcut')
        if adapter is None:
            return ('pause','flashcut_route_unavailable','The separate Gemini flash-cut route is unavailable.',
                    'Configure and qualify the flash-cut route; legacy analysis cannot replace mandatory audiovisual evidence.')
        if not run.state.get('source_evidence_job'):
            prepared=self.s.source_work.prepare(run.id,run.params['flashcut_policy'])
            run.state.update(source_evidence_job=prepared['job_id'],source_evidence_id=prepared['evidence_id'],flashcut_substage='local_evidence')
            self.auto._put(run);return 'wait'
        result=self.auto._jobs(run,[run.state['source_evidence_job']],'source_evidence_failed')
        if result!='next':return result
        eid=run.state['source_evidence_id'];record=self.s.source_evidence.get(eid)
        from ..analysis.source_evidence import binding_from_db
        if binding_from_db(self.s.db,run.id)!=record['binding']:
            raise ContractError('source_evidence_stale','binding','Source or transcript changed; preserve the old operations and prepare a new run.')
        ledger=AnalysisEnvelope(self.s.source_evidence,adapter)
        if not record['analysis_plan']:
            plan=build_analysis_plan(self.s.source_evidence,eid,adapter,self.auto._transcript(run))
            ledger.freeze(eid,plan)
        else:
            plan=self.s.source_evidence.blobs.read(record['analysis_plan'])
        if not run.state.get('flashcut_envelope_checked'):
            gap=self.auto._cover(run,{'usd_micros':plan['envelope']['reserve_usd_micros']},providers=(adapter.name,))
            if gap:return ('pause','budget_exhausted',gap,'Approve the complete frozen analysis envelope, including at most two clarification rounds.')
            run.state.update(flashcut_envelope_checked=plan['identity'],flashcut_quote=plan['envelope'])
            self.auto._put(run)
        self._advice(run,eid)
        if run.state.get('jev_status')=='waiting':
            run.state['flashcut_substage']='optional_prioritization';self.auto._put(run);return 'wait'
        run.state['flashcut_substage']='understanding'
        for request in plan['requests']:ledger.claim(eid,request)
        result=self.auto._run_effect(run,'analysis',adapter.name,adapter.model,plan['requests'],'flashcut_analysis')
        if result!='wait':return result
        if run.state.get('flashcut_format_recovery'):
            from .flashcut_format_recovery import FlashcutFormatRecovery
            result,outputs=FlashcutFormatRecovery(self.auto).collect(run,plan)
        elif run.state.get('flashcut_response_recovery'):
            from .flashcut_recovery import FlashcutResponseRecovery
            result, outputs = FlashcutResponseRecovery(self.auto).collect(run, plan)
        else:
            result=self.auto._jobs(run,run.state['flashcut_analysis_jobs'],'flashcut_analysis_failed')
            if (result!='next' and isinstance(result,tuple)
                    and result[0]=='pause' and result[1]=='flashcut_analysis_failed'
                    and not run.state.get('flashcut_response_recovery')):
                from .policies import run_spending_policy
                if run_spending_policy(run.params):
                    from .flashcut_recovery import FlashcutResponseRecovery
                    try:
                        FlashcutResponseRecovery(self.auto).enable(
                            run, 'auto-pipeline', automatic=True)
                    except ContractError as error:
                        if error.code == 'budget_exhausted':
                            return ('pause', 'budget_exhausted', error.detail,
                                    'The bounded analysis recovery exceeds an applicable ceiling. Raise only the named ceiling or start a new run; the original request will not be replayed.')
                    else:
                        self.auto._put(run)
                        return 'next'
            outputs=([self.s.commands.get(j)['command']['result']['result'] for j in run.state['flashcut_analysis_jobs']]
                     if result == 'next' else [])
        if result!='next':return result
        if any(o.get('binding')!=plan['binding'] for o in outputs):
            raise ContractError('analysis_media_mismatch','provider_result')
        overview=outputs[0].get('analysis')
        if not overview:raise ContractError('analysis_evidence_unavailable','whole_video_understanding')
        # Supplementary collection validates its own fixed clarification; keep
        # original responses immutable in the understanding bundle.
        pending=set() if run.state.get('flashcut_format_recovery') else set(x for out in outputs for x in out['essential_missing'])
        clarifications=run.state.setdefault('flashcut_clarifications',[])
        for index,request in enumerate(clarifications):
            ledger.claim(eid,request)
            tag=f'flashcut_clarify_{index}'
            result=self.auto._run_effect(run,'analysis',adapter.name,adapter.model,[request],tag)
            if result!='wait':return result
            result=self.auto._jobs(run,run.state[tag+'_jobs'],'flashcut_clarification_failed')
            if result!='next':return result
            output=self.s.commands.get(run.state[tag+'_jobs'][0])['command']['result']['result']
            if output.get('binding')!=plan['binding']:raise ContractError('analysis_media_mismatch','clarification')
            pending.difference_update(request['context']['clarify_ids'])
            pending.update(output['essential_missing']);outputs.append(output)
        if pending:
            if sum(r['clarification_round']>0 for r in self.s.source_evidence.get(eid).get('analysis_requests',[]))>=2:
                return ('pause','flashcut_essential_evidence_unresolved',', '.join(sorted(pending)),
                        'Two clarification rounds are exhausted. Preserve evidence and paid operation identities; obtain a new bounded quote before further analysis.')
            request=self._clarification(plan,sorted(pending))
            ledger.claim(eid,request)
            clarifications.append(request);run.state['flashcut_substage']='clarification'
            self.auto._put(run);return 'wait'
        observations=[{**o,'id':f'{i}:{o["id"]}'} for i,out in enumerate(outputs) for o in out['observations']]
        bundle=self.s.source_evidence.blobs.put({'version':'flashcut_understanding.v1','binding':plan['binding'],
            'overview':overview,'responses':outputs,'observations':observations,'plan_identity':plan['identity']})
        run.state.update(analysis=overview,analysis_source_sha=plan['binding']['source_sha256'],
            flashcut_understanding=bundle,flashcut_substage='complete')
        self.auto._advance(run,'sections');return 'next'

    def _advice(self,run,eid):
        if run.state.get('jev_status') in ('complete','unavailable','unknown_retained','not_needed'):
            return
        adapter=self.s.providers.get('jev_decisions')
        if adapter is None:
            run.state['jev_status']='unavailable';self.auto._put(run);return
        summary=jev_summaries(self.s.source_evidence,eid)
        requests=[]
        for start in range(0,len(summary['candidates']),32):
            candidates=summary['candidates'][start:start+32]
            if any(not c['mandatory'] for c in candidates):
                requests.append({**summary,'candidates':candidates})
        if not requests:
            run.state['jev_status']='not_needed';self.auto._put(run);return
        if len(requests)>20:
            run.state['jev_status']='unavailable';self.auto._put(run);return
        result=self.auto._run_effect(run,'analysis',adapter.name,adapter.model,requests,'flashcut_jev')
        if result!='wait':
            run.state['jev_status']='unavailable';self.auto._put(run);return
        jobs=run.state['flashcut_jev_jobs'];outputs=[]
        for jid in jobs:
            row=self.s.db.uow().jobs.get(jid)
            attempts=self.s.db.conn.execute('SELECT status FROM attempts WHERE job_id=?',(jid,)).fetchall()
            if any(a['status'] in ('unknown','dispatching') for a in attempts):
                run.state['jev_status']='unknown_retained';self.auto._put(run);return
            if row['status'] in ('failed','blocked','cancelled'):
                run.state['jev_status']='unavailable';self.auto._put(run);return
            if row['status']!='succeeded':
                run.state['jev_status']='waiting';self.auto._put(run);return
            outputs.append(self.s.commands.get(jid)['command']['result']['result'])
        run.state['jev_advice']=self.s.source_evidence.blobs.put({'mode':'shadow','responses':outputs})
        run.state['jev_status']='complete';self.auto._put(run)

    def _clarification(self,plan,pending):
        from ..analysis.flashcut_requests import build_clarification_request
        return build_clarification_request(plan,pending)
