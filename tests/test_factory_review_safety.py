"""Behavioral regression coverage for spending, resume, evidence and exports."""
import json
import subprocess
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from test_factory_application import application  # noqa: F401
from test_factory_autorun import stack, make_seed, launch
from modules.factory.autorun.service import AutoRunService
from modules.factory.budget import BudgetService
from modules.factory.domain.errors import ContractError
from modules.factory.store import Database


def test_fixed_run_cap_cannot_be_topped_up_or_bypassed(application):
    s, _, act, _, root = stack(application)
    run = launch(act, make_seed(act, root))
    bid = run['params']['spending_policy']['budget_id']
    result = act('post', '/api/budgets', {'id': bid, 'unit': 'usd_micros', 'scope': 'experiment',
        'scope_key': run['id'], 'ceiling': 100_000_000, 'reviewer': 'fixture', 'evidence': 'fixture'})
    assert result.status_code == 400
    budget = BudgetService(s.db)
    assert budget.available(bid) == 50_000_000
    with pytest.raises(ContractError, match='run_guardrail_mismatch'):
        budget.create_budget(bid, 'usd_micros', 'experiment', run['id'], 100_000_000)
    # Historical corruption must fail closed on both reads and reservations.
    s.db.conn.execute('UPDATE budgets SET cap_amount=100000000 WHERE id=?', (bid,))
    with pytest.raises(ContractError, match='run_guardrail_mismatch'):
        budget.available(bid)
    with pytest.raises(ContractError, match='run_guardrail_mismatch'):
        budget.reserve('corrupt-cap', [(bid, 60_000_000)])


def test_registered_proxy_is_retained_and_unregistered_proxy_rejected(application):
    s, _, act, _, root = stack(application)
    seed_id = make_seed(act, root)
    seed = s.seeds.get(seed_id)
    s.seeds.attach_media(seed_id, seed.source_asset_id, role='analysis')
    run = launch(act, seed_id, analysis_asset_id=seed.source_asset_id)
    assert run['params']['analysis_asset_id'] == seed.source_asset_id
    with pytest.raises(ContractError, match='analysis_proxy_mismatch'):
        s.autorun.create({
            'seed_id':seed_id, 'analysis_asset_id':'wrong', 'voice_id':'fixture', 'budget_ids':['credits-usd']})


def test_language_can_change_before_translation_but_not_after_planning(application):
    s, _, act, _, root = stack(application)
    created = launch(act, make_seed(act, root))
    run = s.autorun.get(created['id'])
    run.stage, run.status, run.pause = 'script', 'paused', {'code':'capability_unavailable'}
    s.autorun._put(run)
    changed = s.autorun.resume(run.id, {'set_params':{'language':'zh'}})
    assert changed['params']['language'] == 'zh'
    run = s.autorun.get(run.id)
    run.status, run.state['translate_plan'] = 'paused', 'already-planned'
    s.autorun._put(run)
    with pytest.raises(ContractError, match='new_run_required'):
        s.autorun.resume(run.id, {'set_params':{'language':'en'}})


def test_expired_undispatched_effect_gets_fresh_quote_and_authority(application):
    s, _, act, _, root = stack(application)
    run = s.autorun.get(launch(act, make_seed(act, root))['id'])
    request = {'model':'eleven_v3','voice_id':'voice-fixture','text':'hello'}
    plan = s.effect_work.prepare('tts', 'elevenlabs', 'eleven_v3', [request])
    auth = s.effect_work.authorize(plan['id'], {'plan_hash':plan['plan_hash'], 'reviewer':'fixture',
        'ceilings':{'elevenlabs_credits':100}, 'budget_ids':run.params['budget_ids'], 'valid_until':run.params['valid_until']})
    s.db.conn.execute("UPDATE records SET body=json_set(body,'$.valid_until','2000-01-01T00:00:00Z') WHERE kind='authorization' AND id=?", (auth['authorization_id'],))
    run.state.update(tts_plan=plan['id'], tts_auth=auth['authorization_id'])
    assert s.autorun._run_effect(run,'tts','elevenlabs','eleven_v3',[request],'tts') == 'wait'
    assert run.state['tts_plan'] != plan['id']
    assert run.state['tts_auth'] != auth['authorization_id']
    assert run.state['tts_plan_seq'] == 1
    assert s.db.conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    jobs = list(run.state['tts_jobs'])
    assert s.autorun._run_effect(run,'tts','elevenlabs','eleven_v3',[request],'tts') == 'wait'
    assert run.state['tts_jobs'] == jobs


def test_translation_retry_is_bounded_and_unknown_attempt_is_preserved(application):
    s, _, act, _, root = stack(application)
    run = s.autorun.get(launch(act, make_seed(act, root))['id'])
    cmd = s.commands.enqueue('effect', {'plan_id':'invalid-translation','operation':'0','authorization_id':'fixture'}, identity='translation-fixture')
    jid = cmd['job_id']
    s.db.conn.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (jid,))
    run.stage, run.pause = 'script', {'code':'translation_incomplete'}
    run.state.update(translate_jobs=[jid],translate_plan='invalid-translation')
    s.autorun._reset_budget_blocked_effect(run)
    assert 'translate_jobs' not in run.state
    assert run.state['translation_retries'] == 1
    run.state.update(translate_jobs=[jid],translate_plan='retry-translation')
    s.autorun._reset_budget_blocked_effect(run)
    assert run.state['translate_jobs'] == [jid]
    run.state['translation_retries'] = 0
    aid = s.executor.prepare(jid, 1, {'fixture':'translation'})
    s.db.conn.execute("UPDATE attempts SET status='unknown' WHERE id=?", (aid,))
    s.autorun._reset_budget_blocked_effect(run)
    assert run.state['translate_jobs'] == [jid]
    assert run.state['translation_retries'] == 0


def test_human_acceptance_does_not_follow_replacement_bytes():
    finals = {k:{'artifact_id':'new-'+k,'composition_id':'comp-'+k} for k in 'ABCD'}
    services = NS(db=None, plan_for=lambda _: {}, providers={}, artifacts=NS(verified_path=lambda aid:aid),
                  quality=NS(binding=lambda path, comp, aid:{'artifact_id':aid,'composition_id':comp}))
    auto = AutoRunService(services)
    auto._finals = lambda _: finals
    auto._recompute_failed_region_checks = Mock()
    auto._mandatory_qc = lambda *_: []
    auto._finish_or_deliver = Mock()
    run = NS(params={'workflow':{'version':2},'visual_reviews':True},
             state={'experiment_id':'exp','qc_human_accepted':True,'qc_human_bindings':{'A':{'artifact_id':'old'}}})
    assert auto._stage_final_qc(run)[1] == 'capability_unavailable'
    auto._finish_or_deliver.assert_not_called()
    assert 'qc_human_accepted' not in run.state


def test_export_audio_accepts_codec_loss_and_rejects_wrong_shifted_or_missing(tmp_path):
    from modules.factory.audio import pcm
    from modules.factory.quality.export_audio import compare_export_audio
    # Varying frequency makes a shifted track observably different.
    samples = pcm.sine(.5, freq=440) + pcm.sine(.5, freq=880) + pcm.sine(.5, freq=660) + pcm.sine(.5, freq=330)
    mix = tmp_path / 'mix.wav'; mix.write_bytes(pcm.write_wav(samples))
    good = tmp_path / 'good.m4a'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(mix),'-c:a','aac',str(good)], check=True, capture_output=True)
    assert compare_export_audio(good, mix)['ok']
    for name, bad in [('wrong',pcm.sine(2, freq=990)),('shift',[0]*2205+samples[:-2205]),('short',samples[:-11025])]:
        path = tmp_path / (name+'.wav'); path.write_bytes(pcm.write_wav(bad))
        assert not compare_export_audio(path,mix)['ok'], name
    assert not compare_export_audio(tmp_path/'missing',mix)['ok']


def test_export_audio_compares_at_export_clock_without_double_resampling(tmp_path):
    import subprocess
    from modules.factory.audio import pcm
    from modules.factory.quality.export_audio import compare_export_audio
    source=tmp_path/'original.wav';export=tmp_path/'export.wav'
    # A high-frequency consonant band near the narration's Nyquist limit:
    # resampling the export BACK to 22.05k removes energy from this band.
    source.write_bytes(pcm.write_wav(pcm.sine(1,freq=10500,amp=2000)))
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),
                    '-ar','48000','-c:a','pcm_s16le',str(export)],check=True)
    result=compare_export_audio(export,source)
    assert result['ok'],result
    assert result['rate']==48000


def test_old_audio_failure_is_remeasured_once_without_forcing_pass(tmp_path):
    from modules.factory.quality.service import QualityService
    from modules.factory.quality.export_audio import COMPARISON_VERSION
    video=tmp_path/'final.mp4';video.write_bytes(b'fixture-identity')
    calls=[]
    def inspect(path,expected):
        calls.append(dict(expected))
        audio={'code':'export_audio_content_mismatch','ok':False,'rate':22050}
        if len(calls)>1:audio.update(comparison_version=COMPARISON_VERSION,rate=48000)
        return {'ok':False,'findings':[{'code':audio['code'],'at':'audio'}],'export_audio':audio}
    q=QualityService(Database(tmp_path/'quality.db'),technical=NS(inspect=inspect))
    q.inspect('old-check',video,{'frames':30,'audio_mix':'original-mix'})
    final={'check_ids':['old-check']}
    q.ensure_export_audio(final,video,tmp_path/'bound-mix')
    q.ensure_export_audio(final,video,tmp_path/'bound-mix')
    assert len(calls)==2
    assert calls[-1]=={'frames':30,'audio_mix':str(tmp_path/'bound-mix')}
    assert q._get('old-check')['verdict']=='fail'


def test_manual_horizon_evidence_can_select_a_winner(tmp_path):
    from test_factory_seed_selection import _experiment, _policy, _pub
    from modules.factory.learning.service import LearningService
    from modules.factory.analytics.service import ReadbackService
    db = Database(tmp_path/'manual.db'); _experiment(db)
    learning = LearningService(db); _policy(learning, seed_policy={'mode':'primary_platform','primary_platform':'youtube'})
    readback = ReadbackService(db,None)
    for key, value in {'A':100,'B':200,'C':90,'D':80}.items():
        pid='manual-'+key
        _pub(db,pid,'vp-exp-1-'+key.lower(),'youtube','post-'+key)
        snap=readback.import_verified_manual(pid, metrics={'views':value}, horizon='48h',
            period={'start':'2026-09-10T09:00:00Z','end':'2026-09-12T09:00:00Z','window_kind':'exact_rolling'},
            source_name='studio',reviewer='operator',evidence='saved report '+key,observed_at='2026-09-12T10:00:00Z', now='2026-09-22T00:00:00Z')
        assert snap.availability == {'views':'verified_manual'}
        assert 'likes' not in snap.metrics
        assert readback.get_snapshot(pid, '48h')['id'] == snap.id
        assert next(w for w in readback.due(pid, now='2026-09-22T00:00:00Z') if w['horizon'] == '48h')['status'] == 'complete'
    result=learning.select_seed('exp-1',1)
    assert result['winner_variant'] == 'B',result
    with pytest.raises(ContractError, match='manual_window_mismatch'):
        readback.import_verified_manual('manual-A',metrics={'views':10},horizon='48h',
            period={'start':'2026-09-10T09:00:00Z','end':'2026-09-11T09:00:00Z','window_kind':'exact_rolling'},
            source_name='studio',reviewer='operator',evidence='report',observed_at='2026-09-12T10:00:00Z')


def test_process_matching_covers_launchers_without_crossing_checkouts(tmp_path):
    from modules.factory.operations.processes import matches
    root=tmp_path/'project with spaces'; root.mkdir()
    for executable in (str(root/'.venv/bin/python'), '.venv/bin/python'):
        for args in ('worker', '--root . worker', '--root=. worker'):
            command=f'{executable} -m modules.factory.cli {args}'
            assert matches(command,root,root,'worker')
            assert not matches(command,tmp_path/'other',root,'worker')
            assert not matches(command,root,root,'serve')
        assert not matches(f'{executable} -m modules.factory.cli --root ../other worker',root,root,'worker')


def test_legacy_boundaries(tmp_path,monkeypatch):
    from modules.analytics.windows import window_hours
    from modules.assemble import task_builder
    from modules.script.shots import split_shots
    assert window_hours([168,48,672]) == {'7d':168,'48h':48,'28d':672}
    with pytest.raises(ValueError):window_hours([48,100])
    monkeypatch.setattr(task_builder,'DATA_DIR',tmp_path/'data')
    with pytest.raises(ValueError):task_builder.write_task({'video_subject':'../outside'})
    with pytest.raises(ValueError,match='at least four'):split_shots('Look here.','Look here.')


def test_replacement_final_gets_new_delivery_and_old_pending_delivery_blocks(tmp_path):
    from modules.factory.autorun.policies import new_policies
    db = Database(tmp_path/'delivery.db')
    job = {'status':'succeeded'}
    store = NS(conn=db.conn, uow=lambda: NS(jobs=NS(get=lambda _:job)))
    svc=NS(db=store,config={'mode':'offline','drive_folder_id':'folder'},
        delivery=NS(drive=NS(expected_account='fixture-drive')), _final_checks=lambda _:[],
        deliver_variant=Mock(return_value={'status':'verified','delivery_id':'new-delivery'}))
    auto=AutoRunService(svc); auto._put=Mock(); auto._jobs=lambda *_:'next'
    auto._finals=lambda _:{'A':{'artifact_id':'new-final','sha256':'new-hash','binding':{}}}
    run=NS(experiment_id='exp',notes=[],params={'policies':new_policies(authorized_destination=True),
        'visual_reviews':True,'workflow':{'version':2},'delivery_folder_id':'folder',
        'delivery_account':'fixture-drive','valid_until':'2099-01-01T00:00:00Z'},
        state={'delivery_jobs':{'A':{'job_id':'old-delivery'}},'experiment_revision':2})
    assert auto._finish_or_deliver(run)[1] == 'delivery_unverified'
    svc.deliver_variant.assert_called_once()
    assert run.state['delivery_jobs']['A']['final_binding']['sha256'] == 'new-hash'
    svc.deliver_variant.reset_mock(); job['status']='running'
    run.state['delivery_jobs']={'A':{'job_id':'old-delivery'}}
    assert auto._finish_or_deliver(run)[1] == 'prior_delivery_inflight'
    svc.deliver_variant.assert_not_called()


def test_loop_post_slots_are_atomic_and_idempotent(tmp_path):
    from test_factory_rounds import _setup, _rounds, _freeze
    from modules.factory.services.publication_work import PublicationWork
    db=Database(tmp_path/'loop.db'); _setup(db); rounds=_rounds(db)
    _freeze(rounds,max_posts=1,valid_until='2099-01-01T00:00:00Z',allowed_providers=['upload_post'],allowed_accounts=['account'])
    work=PublicationWork(NS(db=db,rounds=rounds))
    first={'id':'first','experiment_id':'exp-1','provider':'upload_post','account_id':'account'}
    work._claim_loop_slot(first); work._claim_loop_slot(first)
    with pytest.raises(ContractError,match='post_limit'):
        work._claim_loop_slot({**first,'id':'second'})
    assert work._loop_gate(first) is None


def test_manual_post_and_metrics_are_accessible_through_public_api(application):
    from test_factory_seed_selection import _experiment, _policy
    from modules.factory.testing.fakes import FakePublisher
    from modules.factory.integrations.publisher import UploadPostPublisher
    from modules.factory.publishing.service import PublishingService
    s, _, act, _, root=application
    _experiment(s.db); _policy(s.learning)
    variant=json.loads(s.db.uow().records.get('variantplan','vp-exp-1-a')['body'])
    final={'artifact_id':'registered-final','sha256':'ab'*32}
    # Acceptance and exact-final loading already have integration coverage;
    # keep this route test independent of the slow native render pipeline.
    s._final=lambda _: (variant,final,root/'final.mp4',{'artifact_sha256':final['sha256']})
    s.quality.accept=Mock(return_value={'accepted':True})
    s.publication_work._bound_check_ids=Mock(return_value=['current-check'])
    remote=FakePublisher();remote.plant_post('manual-post')
    s.publishing=PublishingService(s.db,publisher=UploadPostPublisher(transport=remote.transport,verifier=remote.verify_post),accounts={'youtube:acct-main':'acct-main'})
    body={**final,'final_sha256':final['sha256'],'platform':'youtube','account_id':'acct-main',
          'remote_post_id':'manual-post','reviewer':'Operator','evidence':'Reviewed upload receipt'}
    response=act('post','/api/variants/vp-exp-1-a/publications/manual',body,rev=1)
    assert response.status_code == 201,response.text
    pub=response.json()['publication']
    assert pub['manual'] and pub['status']=='public' and pub['remote_post_id']=='manual-post'
    assert pub['final_sha256']==final['sha256']
    result=act('post',f"/api/publications/{pub['id']}/readbacks/manual",{
        'horizon':'48h','metrics':{'views':10},'period':{'start':'2026-09-10T09:00:00Z',
        'end':'2026-09-12T09:00:00Z','window_kind':'exact_rolling'},'observed_at':'2026-09-12T10:00:00Z',
        'source_name':'Studio','reviewer':'Operator','evidence':'Saved exact-window report'})
    assert result.status_code==201,result.text
    assert result.json()['availability']=={'views':'verified_manual'}
    assert s.db.conn.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
    stale=act('post','/api/variants/vp-exp-1-a/publications/manual',{**body,'final_sha256':'cd'*32},rev=1)
    assert stale.status_code==409


def test_expiry_recovery_preserves_partially_completed_batch(application):
    s, _, act, _, root = stack(application)
    run = s.autorun.get(launch(act, make_seed(act, root))['id'])
    jobs = []
    for index, status in enumerate(('succeeded', 'failed')):
        jid = s.commands.enqueue('effect', {'plan_id':'partly-complete','operation':str(index),
            'authorization_id':'expired'}, identity=f'partial-expiry:{index}')['job_id']
        s.db.conn.execute('UPDATE jobs SET status=? WHERE id=?', (status, jid))
        jobs.append(jid)
    run.stage, run.pause = 'tts', {'code':'authorization_expired'}
    run.state.update(tts_plan='partly-complete', tts_auth='expired', tts_jobs=jobs,
                     tts_synth_jobs=jobs, tts_batch_tags=['tts'])
    before = json.loads(json.dumps(run.state))
    s.autorun._reset_budget_blocked_effect(run)
    assert run.state == before
    assert s.db.conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
