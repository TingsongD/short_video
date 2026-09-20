"""Offline diagnostic probes: PASS confirms a remaining defect, not correctness.

PYTHONPATH=. .venv/bin/python -m pytest -q docs/factory-reports/probes/review_2026_09_19_followup.py
"""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from modules.factory.autorun.service import AutoRunService
from modules.factory.autorun.review import auto_review_beats
from modules.factory.domain.errors import ContractError


def qc_setup():
    finals = {k: dict(artifact_id='new-'+k, sha256='hash-'+k,
                      composition_id='comp-'+k) for k in 'ABCD'}
    services = NS(db=None, plan_for=lambda _: {},
                  providers={'audiovisual_analysis': NS(account='fixture', model='fixture')},
                  experiments=NS(_variant=lambda *_: NS(segments=[], changed_factor='', hypothesis='')),
                  commands=NS(get=lambda _: {'command': {'result': {'result': {
                      'review': {'verdict': 'fail', 'notes': ['wrong content']}}}}}))
    auto = AutoRunService(services)
    auto._finals = lambda _: finals
    auto._mandatory_qc = lambda *_: []  # Current finals have passing mandatory checks.
    auto._jobs = lambda *_: 'next'
    auto._put = Mock()
    auto._finish = Mock()
    run = NS(params={'visual_reviews': True}, notes=[],
             state={'experiment_id': 'exp', 'qc_submitted': {
                 k: dict(job_id='review-'+k, artifact_id=f['artifact_id'],
                         sha256=f['sha256']) for k, f in finals.items()},
                 **{'qc_verdict_'+k: 'pass' for k in 'ABCD'}})
    return auto, run


def test_replaced_final_keeps_cached_pass_and_ignores_new_failure():
    auto, run = qc_setup()
    run.state['qc_submitted']['A']['sha256'] = 'old-hash'
    def effect(*args):
        run.state[args[-1]+'_jobs'] = ['new-review-A']
        return 'wait'
    auto._run_effect = effect
    assert auto._stage_final_qc(run) == 'wait'
    assert run.state['qc_verdict_A'] == 'pass'
    auto._stage_final_qc(run)
    auto._finish.assert_called_once_with(run)


def test_human_acceptance_flag_accepts_unreviewed_replacement():
    auto, run = qc_setup()
    run.state = {'experiment_id': 'exp', 'qc_human_accepted': True}
    auto._stage_final_qc(run)
    auto._finish.assert_called_once_with(run)


def test_revision_rebind_reuses_old_dispatch_and_ignores_production_jobs():
    jobs = Mock()
    db = NS(uow=lambda: NS(jobs=jobs), conn=NS(execute=Mock()))
    services = NS(db=db, _current=lambda _: NS(revision=2),
                  run_experiment=Mock())
    auto = AutoRunService(services)
    run = NS(stage='footage', notes=[], state={'experiment_id': 'exp',
             'experiment_revision': 1, 'plan_id': 'old-plan', 'run_job': 'old-dispatch'})
    auto._rebind_current_revision(run)
    assert run.stage == 'quote' and run.state['run_job'] == 'old-dispatch'
    # No production job/attempt lookup happens: production_jobs is never populated.
    jobs.get.assert_not_called()
    db.conn.execute.assert_not_called()
    run.stage = 'run'
    auto._jobs = lambda *_: 'next'
    auto._advance = lambda r, stage: setattr(r, 'stage', stage)
    assert auto._stage_run(run) == 'next'
    services.run_experiment.assert_not_called()
    assert run.stage == 'footage'


@pytest.mark.parametrize('upload_status', ['failed', 'rejected', 'uploaded'])
def test_native_verifier_calls_nonprocessed_upload_public(upload_status):
    from modules.factory.integrations.publisher import youtube_post_verifier
    verify = youtube_post_verifier(lambda _: {'body': {'items': [{
        'status': {'privacyStatus': 'public', 'uploadStatus': upload_status},
        'snippet': {'channelId': 'channel', 'publishedAt': '2026-09-19T00:00:00Z'}}]}})
    assert verify('post')['status'] == 'public'


def test_uncertain_detail_at_media_head_still_becomes_reviewed():
    payload = {'beats': [{'id': 'a', 'role': 'product_reveal', 'start_s': 0,
                         'end_s': 3, 'confidence': 'uncertain',
                         'visual_event': 'Garment detail is obscured and uncertain'}],
               'transcript': [{'start_s': 0, 'end_s': 3, 'text': 'Look here'}]}
    assert auto_review_beats(payload)['beats'][0]['confidence'] == 'reviewed'


def test_advertised_language_resume_is_rejected():
    auto = AutoRunService(NS(db=None))
    auto.get = lambda _: NS(status='paused')
    with pytest.raises(ContractError) as error:
        auto.resume('run', {'set_params': {'language': 'zh'}})
    assert error.value.code == 'param_not_resumable'


def test_translation_recovery_never_clears_dead_effect():
    auto = AutoRunService(NS(db=None))
    run = NS(stage='script', pause={'code': 'translation_incomplete'},
             state={'translate_jobs': ['dead-job'], 'translate_plan': 'old-plan'})
    auto._reset_budget_blocked_effect(run)
    assert run.state['translate_jobs'] == ['dead-job']


def test_source_frame_indices_are_divided_by_output_clock(monkeypatch):
    from modules.factory.autorun import scripts
    # A 10-second 24fps source represented on a 30fps output clock.
    beat = NS(id='b', role='hook', source=NS(start=0, end=240),
              target=NS(start=0, end=300), visual_event='source')
    auto = AutoRunService(NS(db=None, analysis=NS(get=lambda _: NS(
        clock=NS(num=30, den=1), beats=[beat]))))
    auto._transcript = lambda _: [{'start_s': 9, 'end_s': 10, 'text': 'last passage'}]
    captured = {}
    class StopProbe(Exception):
        pass
    def capture(beats, transcript):
        captured.update(beats=beats, transcript=transcript)
        raise StopProbe
    monkeypatch.setattr(scripts, 'adapt', capture)
    run = NS(state={'blueprint_id': 'bp'}, params={'language': 'en'})
    with pytest.raises(StopProbe):
        auto._stage_script(run)
    assert captured['beats'][0]['end_s'] == 8
    from modules.factory.analysis.analyzer import assign_passages
    assert len(assign_passages(captured['beats'], captured['transcript'])['unplaced']) == 1


def test_selected_analysis_proxy_is_dropped_by_create():
    auto = AutoRunService(NS(db=None, seeds=NS(get=lambda _: NS())))
    auto.budgets = NS(available=lambda _: 100)
    auto._put = Mock()
    auto._enqueue_step = Mock()
    result = auto.create({'seed_id': 'seed', 'voice_id': 'voice',
                          'budget_ids': ['cap'], 'analysis_asset_id': 'proxy'})
    assert 'analysis_asset_id' not in result['params']


def test_renewed_expiry_reuses_expired_authorization():
    import json
    old_auth = {'binding': {'id': 'plan'}, 'valid_until': '2000-01-01T00:00:00Z'}
    effects = NS(get=lambda _: {'id': 'plan'}, authorize=Mock(), queue=Mock(
        side_effect=ContractError('authorization_expired', 'valid_until')))
    auto = AutoRunService(NS(db=NS(uow=lambda: NS(records=NS(
        get=lambda *_: {'body': json.dumps(old_auth)}))), effect_work=effects,
        providers={'fixture': NS(account='fixture')}))
    run = NS(state={'tts_plan': 'plan', 'tts_auth': 'expired-auth'},
             params={'valid_until': '2099-01-01T00:00:00Z'})
    with pytest.raises(ContractError) as error:
        auto._run_effect(run, 'tts', 'fixture', 'model', [], 'tts')
    assert error.value.code == 'authorization_expired'
    effects.authorize.assert_not_called()
    effects.queue.assert_called_once_with('plan', 'expired-auth')


def test_changed_region_checks_mix_but_not_wrong_final_audio(tmp_path):
    import subprocess
    from modules.factory.audio import pcm
    from modules.factory.quality.regions import RegionGate
    from modules.factory.quality.service import QualityService
    finals = []
    for name, frequency in [('a', 440), ('b', 880)]:
        path = tmp_path / (name+'.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'testsrc2=size=64x64:rate=10:duration=1', '-f', 'lavfi',
                        '-i', f'sine=frequency={frequency}:duration=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-shortest', str(path)], check=True, capture_output=True)
        finals.append(path)
    mix = tmp_path / 'mix.wav'
    mix.write_bytes(pcm.write_wav([100]*48000, rate=48000))
    quality = QualityService(None, region_gate=RegionGate())
    quality._put = Mock()
    assert pcm.decode(finals[0], 48000) != pcm.decode(finals[1], 48000)
    result = quality.check_regions('check', *finals,
        [{'start_frame': 0, 'end_frame': 10}], 10, a_audio=mix, b_audio=mix)
    assert result['verdict'] == 'pass'


def test_stack_orphan_pattern_misses_documented_launcher():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    launcher = (root / 'scripts/factory.sh').read_text()
    down = (root / 'scripts/factory-down.sh').read_text()
    assert 'modules.factory.cli --root . "$@"' in launcher
    assert 'pgrep -f "$PYBIN -m modules.factory.cli $marker"' in down
    python = str(root / '.venv/bin/python')
    command = f'{python} -m modules.factory.cli --root . worker'
    assert re.search(f'{python} -m modules.factory.cli worker', command) is None
