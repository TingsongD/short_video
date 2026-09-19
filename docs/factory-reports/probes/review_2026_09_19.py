"""Offline defect-confirming probes. Passing means the documented defect exists.

Run: PYTHONPATH=. .venv/bin/python -m pytest -q docs/factory-reports/probes/review_2026_09_19.py
"""
import copy
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from modules.factory.autorun.review import inspect_asset, auto_review_beats
from modules.factory.autorun.service import AutoRun, AutoRunService
from modules.factory.budget import BudgetService
from modules.factory.domain.errors import ContractError
from modules.factory.scheduler.scheduler import Scheduler
from modules.factory.services.app import FactoryServices
from modules.factory.services.effect_work import EffectWork
from modules.factory.store import Database


def test_music_remaining_balance_becomes_operation_charge(tmp_path):
    from modules.factory.providers.music import MusicAdapter
    adapter = MusicAdapter(tmp_path / 'music', transport=lambda *_: (
        200, {'x-credits-remaining': '12000'}, b'x' * 2048))
    _, _, receipt = adapter.execute({'model': 'music_v1', 'prompt': 'instrumental',
                                     'music_length_ms': 3000})
    assert receipt['actual_credits'] == 12000


def test_normalized_alignment_rejects_valid_raw_alignment(tmp_path):
    import base64
    import json
    from modules.factory.providers.elevenlabs import ElevenLabsAdapter
    from modules.factory.testing.fakes import ProviderError
    def alignment(text):
        return {'characters': list(text),
                'character_start_times_seconds': [0] * len(text),
                'character_end_times_seconds': [1] * len(text)}
    payload = {'audio_base64': base64.b64encode(b'audio').decode(),
               'alignment': alignment('2'), 'normalized_alignment': alignment('two')}
    adapter = ElevenLabsAdapter(tmp_path / 'tts', transport=lambda *_: (
        200, {}, json.dumps(payload).encode()))
    with pytest.raises(ProviderError) as e:
        adapter.execute({'model': 'eleven_v3', 'voice_id': 'voice', 'text': '2'})
    assert e.value.code == 'malformed_tts_response'


def test_failed_scan_is_reported_as_pass(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', Mock(side_effect=OSError('missing binary')))
    verdict, notes = inspect_asset('/not-read.mp4', {
        'duration_s': 8, 'streams': [{'codec_type': 'video', 'codec_name': 'h264',
                                    'width': 720, 'height': 1280}]},
        {'kind': 'video', 'min_duration_s': 8})
    assert verdict == 'pass' and 'black/frozen scan' in notes[0]


def test_estimated_settlement_cannot_be_corrected(tmp_path):
    db = Database(tmp_path / 'test.db')
    try:
        b = BudgetService(db)
        b.create_budget('cap', 'usd_micros', 'aggregate', cap=100)
        rid = b.reserve('request', [('cap', 80)])
        b.settle(rid, 'usage_estimate', {'cap': 80}, 'estimated usage')
        with pytest.raises(ContractError) as e:
            b.settle(rid, 'invoice_confirmed', {'cap': 95}, 'invoice evidence')
        assert e.value.code == 'settlement_identity_conflict'
        assert b.available('cap') == 20
    finally:
        db.close()


def test_requested_visual_review_silently_skipped():
    auto = AutoRunService(NS(db=None, providers={}))
    auto._finish = Mock()
    run = NS(params={'visual_reviews': True}, notes=[])
    assert auto._stage_final_qc(run) == 'next'
    auto._finish.assert_called_once_with(run)


def test_old_visual_result_is_bound_to_replacement_final():
    quality = NS(binding=lambda path, comp, art: {'artifact_id': art},
                 record_verdict=Mock())
    services = NS(db=None, providers={'audiovisual_analysis': NS(account='fixture')},
                  commands=NS(get=lambda _: {'command': {
                      'input': {'artifact_sha256': 'old-hash'},
                      'result': {'result': {'review': {'verdict': 'pass'}}}}}),
                  experiments=NS(_variant=lambda *_: NS()), quality=quality,
                  artifacts=NS(verified_path=lambda _: '/new-final'))
    auto = AutoRunService(services)
    auto._jobs = lambda *_: 'next'
    auto._finish = Mock()
    auto._finals = lambda _: {'A': {'artifact_id': 'new-artifact',
                                  'sha256': 'new-hash', 'composition_id': 'new-comp'}}
    run = NS(params={'visual_reviews': True},
             state={'experiment_id': 'exp', 'qc_jobs': ['old-qc-job']})
    assert auto._stage_final_qc(run) == 'next'
    assert quality.record_verdict.call_args.args[1] == 'new-hash'
    assert quality.record_verdict.call_args.kwargs['binding']['artifact_id'] == 'new-artifact'


def test_resume_does_not_update_limits_or_expiry():
    auto = AutoRunService(NS(db=None))
    run = AutoRun(schema_version='autorun.v1', id='a', status='paused',
                  params={'limits': {'usd_micros': 1}, 'valid_until': 'expired'},
                  pause={'code': 'limit_too_low'})
    auto.get = lambda _: run
    auto._put = lambda _: None
    auto._enqueue_step = lambda _: None
    auto.resume('a', {'limits': {'usd_micros': 100}, 'valid_until': 'renewed'})
    assert run.params['limits']['usd_micros'] == 1
    assert run.params['valid_until'] == 'expired'


def test_repeated_copy_gets_only_one_segment_fit():
    fit = Mock(return_value={'job_id': 'fit-1'})
    segs = [{'id': 'intro', 'copy': 'Hello again'},
            {'id': 'ending', 'copy': 'Hello again'}]
    services = NS(db=None,
                  experiments=NS(_variant=lambda *_: NS(segments=segs)),
                  audio_work=NS(speech=NS(normalize=lambda s: s), queue_fit=fit))
    auto = AutoRunService(services)
    auto._put = lambda _: None
    auto._jobs = Mock(side_effect=['next', 'wait'])
    run = NS(state={'experiment_id': 'exp', 'experiment_revision': 1,
                    'tts_synth_jobs': {'Hello again': 'synthesis'}}, params={})
    assert auto._stage_tts(run) == 'wait'
    assert fit.call_count == 1
    assert fit.call_args.args[2]['segment_id'] == 'intro'


def test_uncertain_product_detail_is_upgraded_without_new_evidence():
    payload = {'beats': [{'id': 'a', 'role': 'product_reveal',
                         'start_s': 0, 'end_s': 3, 'confidence': 'uncertain',
                         'visual_event': 'Garment detail is obscured and uncertain'}],
               'transcript': [{'start_s': 0, 'end_s': 3, 'text': 'Look here'}],
               'uncertainty': ['Cannot identify the garment detail']}
    out = auto_review_beats(payload)
    assert out['beats'][0]['confidence'] == 'reviewed'
    assert out['uncertainty'] == ['Cannot identify the garment detail']


def test_timeline_coverage_checks_only_three_instants():
    from modules.factory.analysis.deep import ReferenceAnalysisService
    service = object.__new__(ReferenceAnalysisService)
    analysis = NS(acquisition={'duration_s': 100})
    service._editable = lambda *_: analysis
    service._after_edit = lambda a, _: a
    sections = [{'start_s': a, 'end_s': b, 'phase': 'body', 'summary': 'observed'}
                for a, b in [(0, 1), (50, 51), (99, 100)]]
    saved = service.save_timeline('seed', sections, 'reviewer')
    assert sum(s['end_s'] - s['start_s'] for s in saved.timeline) == 3


def test_more_than_twenty_speech_requests_rejected():
    work = EffectWork(NS(providers={'elevenlabs': NS(account='fixture')}))
    with pytest.raises(ContractError) as e:
        work.prepare('tts', 'elevenlabs', 'eleven_v3', [{'text': str(i)} for i in range(21)])
    assert e.value.code == 'invalid_requests'


def test_crash_after_queue_before_run_save_creates_second_effect_set(tmp_path):
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    provider = NS(account='fixture', price=lambda _: {
        'kind': 'usage_estimate', 'unit': 'usd_micros', 'amount': 1,
        'reserve_amount': 1, 'rate_basis': 'fixture', 'valid_until': expiry})
    db = Database(tmp_path / 'test.db')
    try:
        services = FactoryServices(db, scheduler=Scheduler(db),
                                   providers={'audiovisual_analysis': provider})
        services.effect_work = EffectWork(services)
        auto = AutoRunService(services)
        auto.budgets.create_budget('fund', 'usd_micros', 'aggregate', cap=100)
        run = AutoRun(schema_version='autorun.v1', id='run', params={
            'budget_ids': ['fund'], 'valid_until': expiry, 'limits': {}})
        auto._put(run)
        persisted = copy.deepcopy(run)
        auto._put = Mock(side_effect=KeyboardInterrupt('process loss before run save'))
        with pytest.raises(KeyboardInterrupt):
            auto._run_effect(run, 'analysis', 'audiovisual_analysis', 'fixture',
                             [{'task': 'fixture'}], 'analysis')
        before = [r[0] for r in db.conn.execute('SELECT id FROM jobs')]
        assert len(before) == 1
        auto._put = lambda _: None
        auto._run_effect(persisted, 'analysis', 'audiovisual_analysis', 'fixture',
                         [{'task': 'fixture'}], 'analysis')
        after = [r[0] for r in db.conn.execute('SELECT id FROM jobs')]
        assert len(after) == 2 and len(set(after)) == 2
    finally:
        db.close()
