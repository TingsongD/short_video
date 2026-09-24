"""Offline review probes. PASS reproduces the named defect, not correctness.

PYTHONPATH=.:tests .venv/bin/python -m pytest -q docs/factory-reports/probes/review_2026_09_22.py
All application state is isolated in pytest temporary directories.
"""
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from test_factory_application import application  # noqa: F401
from test_factory_autorun import stack, make_seed, launch
from modules.factory.autorun.service import AutoRunService
from modules.factory.budget import BudgetService
from modules.factory.domain.errors import ContractError
from modules.factory.learning.service import LearningService
from modules.factory.store import Database


def test_general_budget_api_can_raise_fixed_run_guardrail(application):
    s, _, act, _, root = stack(application)
    run = launch(act, make_seed(act, root))
    bid = run['params']['spending_policy']['budget_id']
    response = act('post', '/api/budgets', {
        'id': bid, 'unit': 'usd_micros', 'scope': 'experiment',
        'scope_key': run['id'], 'ceiling': 100_000_000,
        'reviewer': 'offline-probe', 'evidence': 'test-only top-up'})
    assert response.status_code == 201, response.text
    assert BudgetService(s.db).available(bid) == 100_000_000
    view = s.autorun.detail(run['id'])['spending_policy']
    assert view['cap_amount'] == 50_000_000
    assert view['committed'] == -50_000_000
    BudgetService(s.db).create_budget('credits-usd', 'usd_micros', 'aggregate', cap=100_000_000)
    assert s.autorun._cover(s.autorun.get(run['id']), {'usd_micros': 60_000_000}) == ''


def test_autorun_create_drops_selected_analysis_proxy(application):
    s, _, act, _, root = stack(application)
    run = launch(act, make_seed(act, root), analysis_asset_id='explicit-proxy')
    assert 'analysis_asset_id' not in run['params']


def test_language_recovery_action_is_rejected(application):
    s, _, act, _, root = stack(application)
    run = launch(act, make_seed(act, root))
    saved = s.autorun.get(run['id'])
    saved.status = 'paused'
    saved.stage = 'script'
    saved.pause = {'code': 'capability_unavailable'}
    s.autorun._put(saved)
    response = act('post', f"/api/autoruns/{run['id']}/resume", {'set_params': {'language': 'zh'}})
    assert response.status_code == 400
    assert response.json()['error'] == 'param_not_resumable'


def test_translation_reset_keeps_completed_invalid_translation_job():
    auto = AutoRunService(NS(db=None))
    run = NS(stage='script', params={'workflow': {'version': 2}},
             pause={'code': 'translation_incomplete'},
             state={'translate_jobs': ['finished-invalid'], 'translate_plan': 'old-plan'})
    auto._reset_budget_blocked_effect(run)
    assert run.state['translate_jobs'] == ['finished-invalid']


def test_expiry_renewal_keeps_cached_expired_authorization():
    old_auth = {'binding': {'id': 'plan'}, 'valid_until': '2000-01-01T00:00:00Z'}
    effects = NS(get=lambda _: {'id': 'plan'}, authorize=Mock(), queue=Mock(
        side_effect=ContractError('authorization_expired', 'valid_until')))
    auto = AutoRunService(NS(config={'mode': 'offline'}, db=NS(uow=lambda: NS(records=NS(
        get=lambda *_: {'body': json.dumps(old_auth)}))), effect_work=effects,
        providers={'fixture': NS(account='fixture')}))
    run = NS(id='auto-probe', state={'tts_plan': 'plan', 'tts_auth': 'expired-auth'},
             params={'valid_until': '2099-01-01T00:00:00Z'})
    with pytest.raises(ContractError, match='authorization_expired'):
        auto._run_effect(run, 'tts', 'fixture', 'model', [], 'tts')
    effects.authorize.assert_not_called()
    effects.queue.assert_called_once_with('plan', 'expired-auth')


def test_human_acceptance_flag_bypasses_replacement_visual_review():
    auto = AutoRunService(NS(db=None, plan_for=lambda _: {}))
    auto._finals = lambda _: {k: {'artifact_id': 'replacement-' + k} for k in 'ABCD'}
    auto._recompute_failed_region_checks = Mock()
    auto._mandatory_qc = lambda *_: []
    auto._finish_or_deliver = Mock(return_value='next')
    auto._run_effect = Mock()
    run = NS(params={'workflow': {'version': 2}, 'visual_reviews': True},
             state={'experiment_id': 'exp', 'qc_human_accepted': True})
    assert auto._stage_final_qc(run) == 'next'
    auto._run_effect.assert_not_called()
    auto._finish_or_deliver.assert_called_once_with(run)


def test_revision_rebind_keeps_old_delivery_jobs(tmp_path):
    db = Database(tmp_path / 'review.db')
    auto = AutoRunService(NS(db=db, _current=lambda _: NS(revision=2)))
    run = NS(stage='final_qc', notes=[], params={'workflow': {'version': 2}},
        state={'experiment_id': 'exp', 'experiment_revision': 1, 'plan_id': 'old-plan',
               'delivery_jobs': {'A': {'job_id': 'old-successful-delivery'}}})
    auto._rebind_current_revision(run)
    assert run.stage == 'quote'
    assert run.state['delivery_jobs']['A']['job_id'] == 'old-successful-delivery'


def test_source_clock_error_survives_new_timing_policy(monkeypatch, tmp_path):
    from modules.factory.autorun import scripts
    db = Database(tmp_path / 'review.db')
    # A 24fps source interval stored by AnalysisService._build; output is 30fps.
    beat = NS(id='b', role='hook', source=NS(start=0, end=240),
              target=NS(start=0, end=300), visual_event='source')
    svc = NS(db=db, config={'mode': 'offline'},
        analysis=NS(get=lambda _: NS(clock=NS(num=30, den=1), beats=[beat])),
        seeds=NS(get=lambda _: NS(source_asset_id='source')),
        artifacts=NS(verified_path=lambda _: tmp_path / 'unused.mp4'),
        ref_analysis=NS(get=lambda _: NS(acquisition={'duration_s': 10})))
    auto = AutoRunService(svc)
    auto._put = Mock()
    # No source read is necessary when the transcript already has valid timing.
    original = db.uow
    db.uow = lambda: NS(artifacts=NS(get=lambda _: {'sha256': 'fixture'}))
    passage = {'start_s': 9, 'end_s': 10, 'text': 'last passage',
               'words': [{'word': 'last', 'start_s': 9, 'end_s': 9.4},
                         {'word': 'passage', 'start_s': 9.5, 'end_s': 10}]}
    auto._transcript = lambda _: [passage]
    from modules.factory.autorun.source_timing import SourceTimingService
    # Restore the real database before entering the real timing implementation.
    review = SourceTimingService.review
    def real_review(self, *args, **kwargs):
        db.uow = original
        return review(self, *args, **kwargs)
    monkeypatch.setattr(SourceTimingService, 'review', real_review)
    captured = {}
    class StopProbe(Exception): pass
    def capture(beats, transcript):
        captured.update(beats=beats, transcript=transcript)
        raise StopProbe
    monkeypatch.setattr(scripts, 'adapt', capture)
    run = NS(id='auto-clock', seed_id='seed', notes=[],
        state={'blueprint_id': 'bp'}, params={'language': 'en', 'source_timing_policy': 'source_timing.v1'})
    with pytest.raises(StopProbe): auto._stage_script(run)
    assert captured['beats'][0]['end_s'] == 8
    from modules.factory.analysis.analyzer import assign_passages
    assert len(assign_passages(captured['beats'], captured['transcript'])['unplaced']) == 1


def test_distinct_pull_timestamps_block_valid_learning_comparison(tmp_path):
    from test_factory_learning import _experiment, _policy, _publish, _rich
    db = Database(tmp_path / 'review.db')
    _experiment(db)
    learning = LearningService(db)
    _policy(learning)
    _publish(db, 'exp-1', {'a': _rich(1000), 'b': _rich(1400), 'c': _rich(900), 'd': _rich(800)})
    assert learning.decide('exp-1', 1)['winner'] == 'B'
    # The coverage, horizon and metric definition stay identical. Only pull time differs.
    db.conn.execute("UPDATE records SET body=json_set(body,'$.observed_at',?) WHERE kind='metricsnapshot' AND id=?",
        ('2026-09-17T12:00:01+00:00', 'snap-pub-exp-1-b-48h'))
    decision = learning.decide('exp-1', 1)
    assert decision['conclusion'] == 'waiting_for_data'
    assert 'incompatible observation windows or source definitions' in decision['limitations']


def test_scoped_winners_never_count_for_template_promotion(tmp_path):
    from test_factory_seed_selection import _experiment, _policy, _lanes
    db = Database(tmp_path / 'review.db')
    _experiment(db)
    learning = LearningService(db)
    _policy(learning)
    _lanes(db, 'exp-1', ['youtube', 'tiktok'], {
        'A': {'youtube': 500, 'tiktok': 400}, 'B': {'youtube': 800, 'tiktok': 700},
        'C': {'youtube': 300, 'tiktok': 300}, 'D': {'youtube': 200, 'tiktok': 100}})
    assert learning.decide('exp-1', 1, platform='tiktok')['winner'] == 'B'
    assert learning.independent_experiments('fmt-1') == set()


def test_disqualified_tie_blocks_eligible_seed_winner():
    learning = LearningService(None)
    policy = {'practical_lift': 0.3}
    sp = {'mode': 'primary_platform', 'primary_platform': 'youtube', 'min_margin': 0}
    table = {k: {'value': v, 'guardrails': 'bad' if k in 'BD' else 'ok',
                 'exposure_ok': True} for k, v in {'A': 100, 'B': 300, 'C': 200, 'D': 300}.items()}
    out = learning._evaluate_seed(policy, sp, {'youtube': {'status': 'ok', 'table': table}}, ['youtube'])
    assert out[0] == 'inconclusive'
    assert out[2]['tie'] == ['B', 'D']


def test_frozen_per_platform_exposure_and_guardrails_are_ignored(tmp_path):
    from test_factory_seed_selection import _experiment, _policy, _lanes
    db = Database(tmp_path / 'review.db')
    _experiment(db)
    learning = LearningService(db)
    sp = {'mode': 'primary_platform', 'primary_platform': 'youtube',
          'per_platform': {'youtube': {'primary_metric': 'views', 'min_exposure': 1000,
                                      'guardrails': {'avg_view_pct': 50}}}}
    _policy(learning, seed_policy=sp)
    _lanes(db, 'exp-1', ['youtube'], {'A': {'youtube': 100}, 'B': {'youtube': 200},
                                   'C': {'youtube': 90}, 'D': {'youtube': 80}})
    result = learning.select_seed('exp-1', 1)
    assert result['outcome'] == 'champion'
    assert result['winner_variant'] == 'B'


def test_seed_selection_accepts_mixed_window_definitions(tmp_path):
    from test_factory_seed_selection import _experiment, _policy, _lanes
    db = Database(tmp_path / 'review.db')
    _experiment(db)
    learning = LearningService(db)
    _policy(learning, seed_policy={'mode': 'primary_platform', 'primary_platform': 'youtube'})
    _lanes(db, 'exp-1', ['youtube'], {'A': {'youtube': 100}, 'B': {'youtube': 200},
                                   'C': {'youtube': 90}, 'D': {'youtube': 80}})
    db.conn.execute("UPDATE records SET body=json_set(body,'$.requested_period.window_kind','source_calendar', '$.query_version','other-definition') WHERE kind='metricsnapshot' AND id=?",
                    ('snap-pub-exp-1-b-youtube-48h',))
    result = learning.select_seed('exp-1', 1)
    assert result['outcome'] == 'champion'
    assert result['winner_variant'] == 'B'


def test_manual_metrics_cannot_be_selected_as_horizon_evidence(tmp_path):
    from test_factory_seed_selection import _experiment, _policy, _pub
    from modules.factory.analytics.service import ReadbackService
    db = Database(tmp_path / 'review.db')
    _experiment(db)
    learning = LearningService(db)
    _policy(learning, seed_policy={'mode': 'primary_platform', 'primary_platform': 'youtube'})
    readback = ReadbackService(db, None)
    for key, value in {'A': 100, 'B': 200, 'C': 90, 'D': 80}.items():
        pid = 'manual-' + key.lower()
        _pub(db, pid, f'vp-exp-1-{key.lower()}', 'youtube', 'post-' + key)
        readback.import_manual(pid, metrics={'views': value}, period={
            'start': '2026-09-10T00:00:00Z', 'end': '2026-09-12T00:00:00Z',
            'horizon_hours': 48, 'window_kind': 'exact_rolling'}, confidence='high', source_name='operator')
    assert learning.select_seed('exp-1', 1)['outcome'] == 'waiting'


@pytest.mark.parametrize('upload_status', ['failed', 'rejected', 'uploaded'])
def test_failed_or_unprocessed_upload_is_verified_public(upload_status):
    from modules.factory.integrations.publisher import youtube_post_verifier
    verify = youtube_post_verifier(lambda _: {'body': {'items': [{
        'status': {'privacyStatus': 'public', 'uploadStatus': upload_status},
        'snippet': {'channelId': 'channel', 'publishedAt': '2026-09-19T00:00:00Z'}}]}})
    assert verify('post')['status'] == 'public'


def test_old_delivery_job_prevents_upload_of_new_final():
    from modules.factory.autorun.policies import new_policies
    db = NS(uow=lambda: NS(jobs=NS(get=lambda _: {'status': 'succeeded'})),
            conn=NS(execute=lambda *_: NS(fetchall=lambda: [])))
    services = NS(db=db, config={'mode': 'offline', 'drive_folder_id': 'folder'},
                  delivery=NS(drive=NS(expected_account='fixture-drive')), deliver_variant=Mock())
    auto = AutoRunService(services)
    auto._put = Mock()
    auto._finals = lambda _: {'A': {'artifact_id': 'new-final', 'sha256': 'new-hash'}}
    auto._jobs = lambda *_: 'next'
    run = NS(experiment_id='exp', notes=[], params={
        'policies': new_policies(authorized_destination=True), 'visual_reviews': True,
        'workflow': {'version': 2}, 'delivery_folder_id': 'folder', 'delivery_account': 'fixture-drive'},
        state={'delivery_jobs': {'A': {'job_id': 'old-delivery'}}, 'experiment_revision': 2})
    assert auto._finish_or_deliver(run)[1] == 'delivery_unverified'
    services.deliver_variant.assert_not_called()


def test_wrong_final_audio_passes_mix_comparison(tmp_path):
    from review_2026_09_19_followup import test_changed_region_checks_mix_but_not_wrong_final_audio
    test_changed_region_checks_mix_but_not_wrong_final_audio(tmp_path)


def test_stack_matcher_misses_documented_launcher():
    from review_2026_09_19_followup import test_stack_orphan_pattern_misses_documented_launcher
    test_stack_orphan_pattern_misses_documented_launcher()


def test_auxiliary_route_qualification_expiry_is_only_checked_at_startup(tmp_path, monkeypatch):
    import base64
    from datetime import datetime, timezone
    from modules.factory.providers import configured
    from modules.factory.operations import config
    from modules.factory.autorun.readiness import provider_ready
    from modules.factory.execution.context import dispatch_context
    class Clock(datetime):
        instant = datetime(2026, 9, 21, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None): return cls.instant
    monkeypatch.setattr(configured, 'datetime', Clock)
    monkeypatch.setattr(config, 'credential_loader', lambda *_: lambda: {'ELEVENLABS_API_KEY': 'offline-fixture'})
    (tmp_path / 'connections.json').write_text(json.dumps({
        'enabled': ['elevenlabs'], 'elevenlabs': {
            'account_id': 'fixture', 'model': 'eleven_v3',
            'contract_evidence': 'fixture', 'live_evidence': 'fixture',
            'qualified_until': '2026-09-22T00:00:00Z',
            'pricing': {'credits_per_character': 1, 'valid_until': '2099-01-01T00:00:00Z'}}}))
    routes, *_ = configured.configured_auxiliary(tmp_path, tmp_path, 'live')
    adapter = routes['elevenlabs']
    transport = Mock(return_value=(200, {}, json.dumps({
        'audio_base64': base64.b64encode(b'fixture').decode(),
        'alignment': {'characters': ['x'], 'character_start_times_seconds': [0],
                      'character_end_times_seconds': [1]}}).encode()))
    adapter.transport = transport  # No network or real credentials.
    Clock.instant = datetime(2026, 9, 23, tzinfo=timezone.utc)
    assert configured.configured_auxiliary(tmp_path, tmp_path, 'live')[0] == {}
    assert adapter.readiness()['live_qualified'] is True
    assert provider_ready(NS(config={'mode': 'live'}, providers=routes), 'elevenlabs') is None
    with dispatch_context({'provider': 'elevenlabs'}):
        adapter.execute({'model': 'eleven_v3', 'voice_id': 'fixture', 'text': 'x'})
    transport.assert_called_once()


def test_legacy_window_names_change_meaning_when_hours_reordered():
    from modules.analytics.windows import window_hours
    assert window_hours([168, 48, 672])['48h'] == 168


def test_legacy_task_subject_can_escape_production_root(tmp_path, monkeypatch):
    from modules.assemble import task_builder
    monkeypatch.setattr(task_builder, 'DATA_DIR', tmp_path / 'data')
    path = task_builder.write_task({'video_subject': '../outside'})
    assert path.resolve() == tmp_path / 'data' / 'outside' / 'mpt_task.json'


def test_legacy_short_script_breaks_minimum_shot_count():
    from modules.script.shots import split_shots
    assert len(split_shots('Look here.', 'Look here.')) == 1


def test_batch_publication_includes_superseded_visual_reviews(tmp_path):
    import hashlib
    from modules.factory.quality.service import QualityService
    from modules.factory.services.publication_work import PublicationWork
    db = Database(tmp_path / 'review.db')
    path = tmp_path / 'final.mp4'
    path.write_bytes(b'offline-fixture')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    binding = {'artifact_sha256': sha, 'artifact_id': 'final-a',
               'composition_id': 'comp-a', 'composition_revision': 1,
               'composition_hash': 'b' * 64, 'plan_hash': 'c' * 64, 'variant_key': 'A'}
    q = QualityService(db, technical=NS(inspect=lambda *_: {'ok': True, 'findings': []}))
    q.binding = lambda *_: binding
    q.visual_scope = lambda _: 'scope-v2'
    q.inspect('technical-a', path, {}, binding=binding)
    q.record_verdict('creative-a', sha, 'creative', 'pass', binding=binding,
                     reviewer='offline-reviewer', reviewer_type='human')
    q.begin_visual(binding, 'scope-v2', 'first')
    failed = q.complete_visual(binding, 'scope-v2', 'first', 'fail')
    q.begin_visual(binding, 'scope-v2', 'second')
    passed = q.complete_visual(binding, 'scope-v2', 'second', 'pass')
    final = {'sha256': sha}
    work = PublicationWork(NS(db=db, _final=lambda _: (None, final, path, binding)))
    ids = work._bound_check_ids({'id': 'variant-a'})
    assert failed['id'] in ids and passed['id'] in ids
    with pytest.raises(ContractError, match='superseded_review'):
        q.accept(path, ids, binding)
    current_ids = [r['id'] for r in q.authoritative_checks([q._get(i) for i in ids], binding)]
    assert q.accept(path, current_ids, binding)['accepted']


@pytest.mark.parametrize('expired,posts', [(True, 0), (False, 1)])
def test_publication_loop_gate_ignores_expiry_and_exhausted_post_cap(tmp_path, expired, posts):
    from test_factory_rounds import _setup, _rounds, _freeze
    from modules.factory.services.publication_work import PublicationWork
    db = Database(tmp_path / 'review.db')
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds, valid_until='2000-01-01T00:00:00Z' if expired else '2099-01-01T00:00:00Z',
            max_posts=1, allowed_providers=['upload_post'], allowed_accounts=['account'])
    rounds._series_posts = lambda _: [{'id': 'already-published'}] * posts
    work = PublicationWork(NS(rounds=rounds))
    assert work._loop_gate({'experiment_id': 'exp-1', 'provider': 'upload_post',
                            'account_id': 'account'}) is None
