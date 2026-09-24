"""Offline regressions for the September 22 code review repairs."""
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from modules.factory.autorun.service import AutoRunService
from modules.factory.domain.errors import ContractError
from modules.factory.learning.service import LearningService
from modules.factory.store import Database


def test_source_clock_error_survives_new_timing_policy(monkeypatch, tmp_path):
    from modules.factory.autorun import scripts
    db = Database(tmp_path / 'review.db')
    # A 24fps source interval stored by AnalysisService._build; output is 30fps.
    beat = NS(id='b', role='hook', source=NS(start=0, end=240),
              target=NS(start=0, end=300), visual_event='source')
    svc = NS(db=db, config={'mode': 'offline'},
        analysis=NS(get=lambda _: NS(clock=NS(num=30, den=1), provenance={'source_clock': {'num':24,'den':1}}, beats=[beat])),
        seeds=NS(get=lambda _: NS(source_asset_id='source')),
        artifacts=NS(verified_path=lambda _: tmp_path / 'unused.mp4'),
        ref_analysis=NS(get=lambda _: NS(acquisition={'duration_s': 10})))
    monkeypatch.setattr('modules.factory.media.analysis_clock.analysis_media',
                        lambda artifacts, aid: {'analysis_artifact_id': aid})
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
    assert captured['beats'][0]['end_s'] == 10
    from modules.factory.analysis.analyzer import assign_passages
    assert len(assign_passages(captured['beats'], captured['transcript'])['unplaced']) == 0

def test_distinct_pull_timestamps_allow_valid_learning_comparison(tmp_path):
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
    assert decision['conclusion'] == 'provisional_winner'
    assert 'incompatible observation windows or source definitions' not in decision['limitations']

def test_scoped_winners_count_for_template_promotion(tmp_path):
    from test_factory_seed_selection import _experiment, _policy, _lanes
    db = Database(tmp_path / 'review.db')
    _experiment(db)
    learning = LearningService(db)
    _policy(learning)
    _lanes(db, 'exp-1', ['youtube', 'tiktok'], {
        'A': {'youtube': 500, 'tiktok': 400}, 'B': {'youtube': 800, 'tiktok': 700},
        'C': {'youtube': 300, 'tiktok': 300}, 'D': {'youtube': 200, 'tiktok': 100}})
    assert learning.decide('exp-1', 1, platform='tiktok')['winner'] == 'B'
    assert learning.independent_experiments('fmt-1') == {'seed-1'}

def test_disqualified_tie_allows_eligible_seed_winner():
    learning = LearningService(None)
    policy = {'practical_lift': 0.3}
    sp = {'mode': 'primary_platform', 'primary_platform': 'youtube', 'min_margin': 0}
    table = {k: {'value': v, 'guardrails': 'bad' if k in 'BD' else 'ok',
                 'exposure_ok': True} for k, v in {'A': 100, 'B': 300, 'C': 200, 'D': 300}.items()}
    out = learning._evaluate_seed(policy, sp, {'youtube': {'status': 'ok', 'table': table}}, ['youtube'])
    assert out[:2] == ('champion', 'C')
    assert 'tie' not in out[2]

def test_frozen_per_platform_exposure_and_guardrails_are_enforced(tmp_path):
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
    assert result['outcome'] != 'champion'
    assert not result['winner_variant']

def test_seed_selection_rejects_mixed_window_definitions(tmp_path):
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
    assert result['outcome'] != 'champion'
    assert not result['winner_variant']

@pytest.mark.parametrize('upload_status', ['failed', 'rejected', 'uploaded'])
def test_failed_or_unprocessed_upload_is_not_public(upload_status):
    from modules.factory.integrations.publisher import youtube_post_verifier
    verify = youtube_post_verifier(lambda _: {'body': {'items': [{
        'status': {'privacyStatus': 'public', 'uploadStatus': upload_status},
        'snippet': {'channelId': 'channel', 'publishedAt': '2026-09-19T00:00:00Z'}}]}})
    assert verify('post')['status'] != 'public'

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
    assert adapter.readiness()['live_qualified'] is False
    assert provider_ready(NS(config={'mode': 'live'}, providers=routes), 'elevenlabs')[1] == 'qualification_expired'
    from modules.factory.providers.preflight import RequestNotSent
    with dispatch_context({'provider': 'elevenlabs'}), pytest.raises(RequestNotSent, match='qualification_expired'):
        adapter.execute({'model': 'eleven_v3', 'voice_id': 'fixture', 'text': 'x'})
    transport.assert_not_called()

def test_batch_publication_excludes_superseded_visual_reviews(tmp_path):
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
    work = PublicationWork(NS(db=db, quality=q, _final=lambda _: (None, final, path, binding)))
    ids = work._bound_check_ids({'id': 'variant-a'})
    assert failed['id'] not in ids and passed['id'] in ids
    assert q.accept(path, ids, binding)['accepted']
    current_ids = [r['id'] for r in q.authoritative_checks([q._get(i) for i in ids], binding)]
    assert q.accept(path, current_ids, binding)['accepted']

@pytest.mark.parametrize('expired,posts', [(True, 0), (False, 1)])
def test_publication_loop_gate_enforces_expiry_and_exhausted_post_cap(tmp_path, expired, posts):
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
                            'account_id': 'account'}) == ('loop_expired' if expired else 'post_limit')
