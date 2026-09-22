"""New profile: real helper/native rendering; fake remote transports only."""
from copy import deepcopy
from datetime import timedelta
import json
import subprocess
import pytest

from test_factory_autorun import application, stack, launch, make_seed, ANALYZE, EXPIRY


@pytest.fixture(autouse=True)
def stop_test_owned_runtimes(application):
    yield
    from modules.factory.rendering.hypit_build import LAUNCHER
    for config in application[0].composition.root.glob('*/r*/hypit.runtime.json'):
        result=subprocess.run([str(LAUNCHER),'runtime','down','--workspace',str(config.parent),'--json'],
            capture_output=True,text=True,timeout=45)
        assert result.returncode==0,'Test-owned runtime cleanup could not be verified'


@pytest.mark.parametrize('recover_truncated', [False, True, 'budget_refused', 'structured', 'schema_rejected', 'format_recovery', 'format_missing', 'format_budget_refused', 'format_gap_prose', 'format_remote_error'])
def test_new_flashcut_profile_reaches_native_compare_and_verified_delivery(application, recover_truncated):
    from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer
    from modules.factory.analysis.editorial_planning import PROMPT as EDIT_PROMPT
    s,client,act,worker,root=stack(application)
    from test_factory_future_workflow import distinct_transport
    distinct_transport(s)
    base=s.providers['audiovisual_analysis']
    calls=[]
    format_case=str(recover_truncated).startswith('format_')
    def transport(method,url,body,headers):
        payload=json.loads(body);parts=payload['contents'][0]['parts']
        text=parts[-1]['text'];calls.append(payload)
        compact=text.startswith('FLASHCUT_UNDERSTANDING_V2')
        if (recover_truncated=='schema_rejected' or format_case) and payload['generationConfig'].get('responseSchema') and not compact:
            return 400,{},b'{"error":{"code":400,"message":"Request contains an invalid argument.","status":"INVALID_ARGUMENT"}}'
        if text.startswith(EDIT_PROMPT):
            inp=json.loads(text[len(EDIT_PROMPT):]);variants={}
            for key,variant in inp['variants'].items():
                word=variant['passages'][0]['words'][1]
                variants[key]={'events':[{'id':'flash','observation_id':'0:flash','kind':'cut','required':True,
                    'source_time':'0.5','duration_frames':2,'footage_id':'b1','source_in_frame':0,
                    'anchor':{'kind':'speech','passage_id':'p0','word_index':1,'text':word['text'],'edge':'start'}}],
                    'coverage':[{'observation_id':'0:flash','event_id':'flash'}]}
            response={'variants':variants}
        else:
            context=json.loads(text.split('Source context follows:\n',1)[1])
            whole=context['scope']=='whole'
            if recover_truncated=='format_remote_error' and compact and context['scope']=='clarification':
                return 500,{},b'{"error":{"code":500,"message":"Internal error encountered.","status":"INTERNAL"}}'
            gap_window=(recover_truncated=='format_gap_prose' and context['scope']=='window'
                        and any(p.get('text','').startswith('Media identity and source clock: ') and
                            json.loads(p['text'].split(': ',1)[1])['id']=='window:0' for p in parts))
            if recover_truncated and (whole or gap_window) and payload['generationConfig']['maxOutputTokens'] == 8192 and not payload['generationConfig'].get('responseSchema'):
                return 200, {}, json.dumps({'candidates': [{'finishReason': 'MAX_TOKENS',
                    'content': {'parts': [{'text': '{"observations": ['}]}}],
                    'usageMetadata': {'promptTokenCount': 100, 'thoughtsTokenCount': 8000}}).encode()
            response={'observations':[],'essential_missing':[]}
            if whole:
                if (recover_truncated in ('structured','schema_rejected') or format_case) and not payload['generationConfig'].get('responseSchema'):
                    return 200, {}, json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(response)}]}}]}).encode()
                overview=deepcopy(ANALYZE)
                overview['creative_context']={'version':'scene.v2','roles':[],'scenes':[
                    {'beat_id':b['id'],'physical_scene':b['visual_event'],'cast':[],'wardrobe':[] if payload['generationConfig'].get('responseSchema') else {},
                     'allowed_transition':'Planned scene change.','source_overlays':[],'environmental_text':[]}
                    for b in overview['beats']]}
                response.update(analysis=overview,observations=[{'id':'flash','kind':'cut','start_s':.5,'end_s':.566666667,
                    'time_basis':'source','description':'A brief fictional insert.','evidence_ids':['source'],
                    'role_ids':[],'text_role':'none','confidence':'observed'}])
            elif gap_window:
                response['essential_missing']=['Video coverage is missing from source time 0.0s to 0.5s.'] if compact else ['malformed legacy gap']
                if compact:response['coverage_gaps']=[{'start_s':0,'end_s':0.5}]
            elif recover_truncated in ('format_missing','format_gap_prose','format_remote_error'):
                if compact:
                    response['observations']=[{'id':'context','kind':'action','start_s':0,'end_s':1,
                        'time_basis':'source','description':'The opening contains the fixture shot.','evidence_ids':['source'],
                        'role_ids':[],'text_role':'none','confidence':'observed'}]
                else:response['essential_missing']=['coverage:first']
        return 200,{},json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(response)}]}}]}).encode()
    s.providers['audiovisual_analysis_flashcut']=FlashcutAnalyzer(root/'flashcut-route',s.artifacts,base.auth,
        'fixture','fixture',{'input_usd_micros_per_million':1,'output_usd_micros_per_million':1,
        'valid_until':EXPIRY,'evidence':'offline-only pricing'},transport=transport)
    run=launch(act,make_seed(act,root),profile_id='flashcut_hypit.v1',delivery_policy='after_qc')
    approved_recovery = False
    approved_format=False
    for _ in range(1200):
        result=worker.tick()
        current=s.autorun.get(run['id'])
        # New runs carry a saved cumulative USD guardrail.  A proven completed
        # response may therefore receive the existing bounded replacement plan
        # automatically, without fabricating human approval.  Keep the later
        # format-recovery boundary manual: it is a distinct quote/identity.
        if current.state.get('flashcut_response_recovery') and not approved_recovery:
            automatic=s.source_evidence.blobs.read(current.state['flashcut_response_recovery'])
            assert automatic['reviewer_type']=='automated'
            assert automatic['reviewer']=='auto-pipeline'
            approved_recovery='automatic'
        if recover_truncated in ('format_missing','format_gap_prose') and approved_format and current.stage!='video_analysis':
            assert current.state['analysis']
            expected=3 if recover_truncated=='format_gap_prose' else 2
            assert sum(c['contents'][0]['parts'][-1]['text'].startswith('FLASHCUT_UNDERSTANDING_V2') for c in calls)==expected
            assert sum(r['clarification_round']>0 for r in s.source_evidence.get(current.state['source_evidence_id'])['analysis_requests'])==1
            if recover_truncated=='format_gap_prose':
                assert len(current.state['flashcut_gap_evidence'])==1
                jid=next(iter(current.state['flashcut_gap_evidence']))
                assert s.commands.get(jid)['status']=='failed'
                assert s.db.conn.execute('SELECT status FROM attempts WHERE job_id=?',(jid,)).fetchone()[0]=='unknown'
            return
        if current.status=='paused' and format_case and approved_recovery and not approved_format:
            from modules.factory.autorun.flashcut_format_recovery import FlashcutFormatRecovery
            recovery=FlashcutFormatRecovery(s.autorun)
            quote=recovery.quote(current)
            before_calls=len(calls)
            if recover_truncated=='format_budget_refused':
                from modules.factory.domain.errors import ContractError
                budget=s.autorun.budgets
                budget.tighten_budget('credits-usd',500-budget.available('credits-usd'),500,'offline operator','Exhausted authority')
                with pytest.raises(ContractError,match='budget_exhausted'):recovery.quote(current)
                assert not s.autorun.get(current.id).state.get('flashcut_format_recovery') and len(calls)==before_calls
                return
            assert quote==recovery.quote(s.autorun.get(current.id))
            assert len(calls)==before_calls
            stale=act('post',f'/api/autoruns/{current.id}/resume',{
                'approve_flashcut_format_recovery':'0'*64,'reviewer':'offline operator'})
            assert stale.status_code in (400,409,422) and 'flashcut_recovery_quote_changed' in stale.text
            assert len(calls)==before_calls
            response=act('post',f'/api/autoruns/{current.id}/resume',{
                'approve_flashcut_format_recovery':quote['identity'],'reviewer':'offline operator'})
            assert response.status_code in (200,202),response.text
            from modules.factory.autorun.service import AutoRunService
            s.autorun=AutoRunService(s)
            approved_format=True
            continue
        if current.status == 'paused' and recover_truncated and not approved_recovery:
            assert current.pause['code'] == 'flashcut_analysis_failed', current.pause
            # Let already authorized sibling requests complete before freezing repair.
            for _ in range(50):
                jobs = [s.commands.get(j) for j in current.state['flashcut_analysis_jobs']]
                if all(j['status'] in ('failed', 'succeeded') for j in jobs): break
                worker.tick()
            if recover_truncated == 'budget_refused':
                budget = s.autorun.budgets
                committed = 500 - budget.available('credits-usd')
                budget.tighten_budget('credits-usd', committed, 500, 'offline operator', 'Test exhausted authority')
                before_calls = len(calls)
                refused = act('post', f'/api/autoruns/{current.id}/resume', {
                    'approve_flashcut_response_recovery': True, 'reviewer': 'offline operator'})
                assert refused.status_code in (400, 409, 422), refused.text
                assert 'budget_exhausted' in refused.text
                assert not s.autorun.get(current.id).state.get('flashcut_response_recovery')
                assert len(calls) == before_calls
                return
            response = act('post', f'/api/autoruns/{current.id}/resume', {
                'approve_flashcut_response_recovery': True, 'reviewer': 'offline operator'})
            assert response.status_code in (200, 202), response.text
            from modules.factory.autorun.service import AutoRunService
            s.autorun = AutoRunService(s)  # Reload service from durable state.
            approved_recovery = True
            continue
        if current.status in ('succeeded','paused','failed'):break
        if result is None:
            future=s.scheduler.clock()+timedelta(seconds=5);s.scheduler.clock=lambda:future
    if recover_truncated=='schema_rejected':
        assert current.status=='paused'
        assert '400' in current.pause['detail']
        assert 'bounded recovery plan' in current.pause['action']
        assert sum(bool(c['generationConfig'].get('responseSchema')) for c in calls)==1
        return
    if recover_truncated=='format_remote_error':
        assert current.status=='paused' and '500' in current.pause['detail']
        assert 'Do not retry' in current.pause['action']
        jid=current.state['flashcut_format_clarify_jobs'][0]
        assert s.db.conn.execute('SELECT status FROM attempts WHERE job_id=?',(jid,)).fetchone()[0]=='unknown'
        before_calls=len(calls)
        assert act('post',f'/api/autoruns/{current.id}/resume',{}).status_code in (200,202)
        for _ in range(10):worker.tick()
        assert len(calls)==before_calls and s.autorun.get(current.id).status=='paused'
        original=s.source_evidence.blobs.read(s.source_evidence.get(current.state['source_evidence_id'])['analysis_plan'])
        body={'approve_flashcut_evidence_reuse':True,'analysis_plan_identity':'0'*64,'reviewer':'offline assistant'}
        stale=act('post',f'/api/autoruns/{current.id}/resume',body)
        assert stale.status_code in (400,409,422) and 'flashcut_recovery_mismatch' in stale.text
        body['analysis_plan_identity']=original['identity']
        bad=act('post',f'/api/autoruns/{current.id}/resume',{**body,'visual_evidence':[{
            'candidate_id':'visual:99999','evidence_ids':[],'description':'Invented frame'}]})
        assert bad.status_code in (400,409,422) and 'invalid_visual_evidence' in bad.text
        assert act('post',f'/api/autoruns/{current.id}/resume',body).status_code in (200,202)
        for _ in range(10):worker.tick()
        # This fixture asks about footage already within the window; generic
        # whole-source context must NOT silently clear its semantic question.
        assert len(calls)==before_calls and s.autorun.get(current.id).status=='paused'
        assert s.autorun.get(current.id).state['flashcut_context_reuse']
        return
    assert current.status=='succeeded',(current.stage,current.pause)
    exp=s._current(current.experiment_id)
    assert exp.packaging['flashcut_policy']['renderer']=='hypit_primary.v1'
    assert s.templates.preview(current.state['template_id'])['spec']['renderer']=='hypit'
    manifest=s.source_evidence.manifest(current.state['source_evidence_id'])
    assert manifest['totals']['visual']==270
    finals=s.autorun._finals(current)
    assert set(finals)==set('ABCD')
    for key,final in finals.items():
        comp=s.db.uow().records.get('composition',final['composition_id'])
        assert json.loads(comp['body'])['renderer']=='hypit'
        assert final['editorial_manifest']['sha256']
        technical=s.quality._get(next(check for check in final['check_ids']
                                      if check.startswith('technical-')))
        temporal=technical['evidence_data']['expected']['temporal']
        assert temporal['version']=='flashcut_temporal_qc.v1'
        assert temporal['caption_alignment']=='final_speech_schedule.v1'
        coverage=technical['evidence_data']['report']['temporal_coverage']
        assert coverage['video_pts']['frames']==exp.packaging['target_frames']
        assert coverage['captions']['pixel_ocr'] is False
        assert coverage['brief_events']['semantic_identity'] is False
        assert coverage['lip_sync']=='not_verified'
    assert sum(any(p.get('text','').startswith(EDIT_PROMPT) for p in c['contents'][0]['parts']) for c in calls)==1
    assert all(any('inlineData' in p for p in c['contents'][0]['parts']) for c in calls[:-1])
    assert current.state['completion_phases']['delivery']=='complete'
    if recover_truncated:
        plan = s.source_evidence.blobs.read(current.state['flashcut_response_recovery'])
        assert len(plan['requests']) == 1 and plan['max_replacements'] == 2
        assert len([c for c in calls if c['generationConfig']['maxOutputTokens'] == 32768
                    and not c['contents'][0]['parts'][-1]['text'].startswith('FLASHCUT_UNDERSTANDING_V2')]) == 1
        original_job = plan['entries'][0]['job_id']
        assert s.commands.get(original_job)['status'] == 'failed'
    if recover_truncated=='format_recovery':
        assert approved_format
        assert sum(c['contents'][0]['parts'][-1]['text'].startswith('FLASHCUT_UNDERSTANDING_V2') for c in calls)==1
