"""Offline prevention at run, provider and scheduler interfaces."""
import copy
from types import SimpleNamespace

import pytest

from modules.factory.autorun.service import AutoRun, AutoRunService
from modules.factory.domain.errors import ContractError
from test_factory_api import env, mut
from test_factory_analysis_timing_recovery import analyzer, payload, failed_attempt
from test_factory_auth_recovery import operation


def test_not_sent_recovery_keeps_google_guidance(operation):
    from modules.factory.services import FactoryServices
    from modules.factory.autorun.recovery import AnalysisRecovery
    from modules.factory.testing.fakes import ProviderError
    db, _, executor, attempt, _, _, calls = operation
    with pytest.raises(ProviderError):
        executor.submit(attempt)
    run = AutoRun(id='not-sent', status='paused', stage='video_analysis',
                  state={'analysis_jobs':['auth-job']}, pause={'code':'analysis_failed'})
    result = AnalysisRecovery(FactoryServices(db)).describe(run)
    assert result['kind'] == 'request_not_sent'
    assert 'Reconnect the configured Google account' in result['message']
    assert 'released' in result['message'] and result['can_resume']
    assert not calls


def test_model_review_claim_and_fake_evidence_cannot_bypass_local_review():
    from modules.factory.autorun.review import auto_review_beats
    raw = payload()
    raw['beats'][0].update(start_s=1, confidence='reviewed', evidence_ids=['invented-frame'])
    result = auto_review_beats(copy.deepcopy(raw))
    assert result['beats'][0]['confidence'] == 'uncertain'
    assert auto_review_beats(copy.deepcopy(raw), {'boundaries':[{'t':1}]})['beats'][0]['confidence'] == 'reviewed'


@pytest.mark.parametrize('worker,capacity,code', [
    ({'available':False}, {}, 'worker_unavailable'),
    ({'available':True,'paused':True,'draining':False}, {}, 'queue_paused'),
    ({'available':True,'paused':False,'draining':False}, {'used':1,'limit':1}, 'queue_capacity_full'),
])
def test_runtime_readiness_refuses_unavailable_work_without_mutation(env, monkeypatch, worker, capacity, code):
    from modules.factory.autorun.readiness import runtime_ready
    _, _, db, s, _ = env
    s.config['mode'] = 'live'
    monkeypatch.setattr(s, 'health', lambda: {'worker':worker})
    monkeypatch.setattr(s.scheduler, 'status_snapshot', lambda: {'capacities':{'dispatch':capacity}})
    before = db.conn.total_changes
    with pytest.raises(ContractError, match=code):
        runtime_ready(s)
    assert db.conn.total_changes == before


def test_blueprint_approval_survives_recovery_and_restart(env, monkeypatch):
    _, _, _, s, _ = env
    raw = payload()
    raw['transcript'][0]['words'] = []
    run = AutoRun(schema_version='autorun.v1', id='resume-review', seed_id='seed',
        stage='blueprint', params={'ai_scene_review':False},
        state={'analysis': copy.deepcopy(raw), 'analysis_reset': True})
    current = [None]
    imports = []
    def get(_):
        if current[0] is None:
            raise ContractError('unknown_blueprint', 'id')
        return current[0]
    def build(seed, data, reviewer, **kwargs):
        imports.append(copy.deepcopy(data))
        current[0] = SimpleNamespace(id='bp-seed', content_hash='reviewed-hash',
            status='draft', provenance={'artifact_sha256':'source', **kwargs.get('provenance', {})})
        return current[0]
    def prepare(*args):
        current[0].status = 'accepted'
    monkeypatch.setattr(s.seeds, 'get', lambda _: SimpleNamespace(source_asset_id='source-art'))
    monkeypatch.setattr(s.artifacts, 'get', lambda _: None, raising=False)
    monkeypatch.setattr(s.ref_analysis, 'get', lambda _: SimpleNamespace(
        source_sha256='source', acquisition={'duration_s':4}, evidence={}))
    s.analysis = SimpleNamespace(get=get, import_observations=build)
    s.blueprints = SimpleNamespace(prepare_automatically=prepare, flags=lambda _: [{'flag':'low_confidence_scene','detail':'b1'}])
    # Real source identity lookup, without needing a media process for this test.
    with s.db.uow() as u:
        u.conn.execute("INSERT INTO artifacts(id,sha256,kind,local_path,status,body,created_at,updated_at) VALUES('source-art','source','video','unused','ready','{}','now','now')")
    s.autorun._put(run)
    assert s.autorun._stage_blueprint(run) == 'next'
    assert run.state['analysis'] == raw, 'machine review must not mutate provider observations'
    resumed = AutoRunService(s).get(run.id)  # Simulate a new worker after restart.
    resumed.stage = 'blueprint'
    assert AutoRunService(s)._stage_blueprint(resumed) == 'next'
    assert resumed.stage == 'template' and len(imports) == 1
    # New source evidence must still invalidate the old accepted blueprint.
    resumed.stage = 'blueprint'
    resumed.state['analysis']['beats'][0]['visual_event'] = 'Changed observation'
    assert AutoRunService(s)._stage_blueprint(resumed) == 'next'
    assert len(imports) == 2
    resumed.state['analysis_source_sha'] = 'changed-source'
    assert AutoRunService(s)._stage_blueprint(resumed)[1] == 'analysis_source_changed'
    assert len(imports) == 2


def test_legacy_current_blueprint_approval_is_not_discarded(env, monkeypatch):
    from modules.factory.domain.clocks import FPS_30, FrameInterval
    _, _, _, s, _ = env
    raw = payload(); raw['transcript'][0]['words'] = []
    run = AutoRun(schema_version='autorun.v1', id='legacy', seed_id='seed',
        stage='blueprint', state={'analysis':raw, 'analysis_reset':True})
    bp=SimpleNamespace(id='bp-seed',content_hash='accepted',status='accepted', clock=FPS_30,
        provenance={'artifact_sha256':'source','uncertainty':[]},
        speech={'transcript':raw['transcript']}, audio={'music_role':'bed'},
        beats=[SimpleNamespace(id='b1',role='hook',visual_event='Motion',target=FrameInterval(0,120),confidence='reviewed')])
    monkeypatch.setattr(s.seeds,'get',lambda _: SimpleNamespace(source_asset_id='source-art'))
    with s.db.uow() as u:
        u.conn.execute("INSERT INTO artifacts(id,sha256,kind,status,body,created_at,updated_at) VALUES('source-art','source','video','ready','{}','now','now')")
    s.analysis=SimpleNamespace(get=lambda _: bp,import_observations=lambda *a,**k: pytest.fail('Current human approval was discarded'))
    s.ref_analysis=SimpleNamespace(get=lambda _: SimpleNamespace(acquisition={'duration_s':4},evidence={}))
    prepared = []
    # This test supplies an in-memory analysis repository. Keep preparation
    # on that same boundary, and require revalidation of the unchanged hash.
    # Real persisted preparation and revision rebinding are covered separately.
    s.blueprints = SimpleNamespace(
        prepare_automatically=lambda blueprint_id, expected_hash:
            prepared.append((blueprint_id, expected_hash)))
    s.autorun._put(run)
    assert s.autorun._stage_blueprint(run)=='next'
    assert run.stage=='template'
    assert prepared == [('bp-seed', 'accepted')]
    assert run.state['blueprint_id'] == 'bp-seed'


def test_analysis_request_uses_provider_schema(tmp_path, monkeypatch):
    ad, request, calls = analyzer(tmp_path, monkeypatch, payload())
    ad.execute(request)
    schema = calls[0]['generationConfig']['responseSchema']
    assert 'beats' in schema['required'] and 'transcript' in schema['required']
    beat = schema['properties']['beats']['items']
    assert beat['properties']['confidence']['enum'] == ['uncertain', 'unresolved']
    assert 'end_s' in beat['required']


@pytest.mark.parametrize('bad_file', ['receipt.json', 'provider-response.json'])
def test_corrupt_saved_response_hint_does_not_break_dashboard(tmp_path, monkeypatch, bad_file):
    import hashlib
    import json
    ad, request, _ = analyzer(tmp_path, monkeypatch, payload())
    aid='hint-attempt'
    wire_hash=hashlib.sha256(json.dumps(request,sort_keys=True,default=str).encode()).hexdigest()
    folder=ad.root / ('sync-' + hashlib.sha256(aid.encode()).hexdigest()[:32])
    folder.mkdir(parents=True,exist_ok=True)
    receipt={'request_hash':wire_hash,'status':'unknown'}
    saved={'http_status':200,'attempt_id':aid,'request_hash':wire_hash}
    for name,body in [('receipt.json',receipt),('provider-response.json',saved)]:
        (folder/name).write_text(json.dumps([] if name==bad_file else body))
    assert ad.saved_response_available(request,aid) is False


def test_unknown_analysis_cannot_resume_into_paid_retry(env):
    client, csrf, db, s, _ = env
    aid, _, _ = failed_attempt(db, cause='response_lost')
    db.conn.execute("UPDATE jobs SET status='failed',blocked_reason='response_lost' WHERE id='invalid-job'")
    run = AutoRun(schema_version='autorun.v1', id='unknown-run', seed_id='seed',
        status='paused', stage='video_analysis', params={'budget_ids':[]},
        state={'analysis_jobs':['invalid-job']}, pause={'code':'analysis_failed'})
    s.autorun._put(run)
    before = db.conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
    response = mut(client, csrf, 'post', '/api/autoruns/unknown-run/resume', json={})
    assert response.status_code == 400 and response.json()['error'] == 'analysis_reconciliation_required'
    assert s.autorun.get(run.id).status == 'paused'
    assert db.conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == before


def test_terminal_capacity_is_repaired_but_unknown_is_retained(env):
    _, _, db, s, _ = env
    aid, _, _ = failed_attempt(db)
    db.conn.execute("UPDATE jobs SET status='failed' WHERE id='invalid-job'")
    db.conn.execute("INSERT INTO capacity_holds(capacity,job_id,holder,fencing,expires_at,retained_reason) VALUES('dispatch','invalid-job','old',0,'2000-01-01','unfinished_remote_op')")
    s.scheduler.reclaim_expired()
    assert db.conn.execute('SELECT COUNT(*) FROM capacity_holds').fetchone()[0] == 1
    db.conn.execute("UPDATE attempts SET status='failed' WHERE id=?", (aid,))
    s.scheduler.reclaim_expired()
    assert db.conn.execute('SELECT COUNT(*) FROM capacity_holds').fetchone()[0] == 0


def test_auth_preflight_blocks_before_a_plan_or_reservation(env):
    _, _, db, s, _ = env
    calls = []
    s.config['mode'] = 'live'
    s.providers['audiovisual_analysis'] = SimpleNamespace(account='test',
        refresh_readiness=lambda: calls.append('readiness') or {'authenticated':False, 'reason':'reauth_required'})
    run = AutoRun(schema_version='autorun.v1', id='preflight', seed_id='seed', params={'budget_ids':[]})
    result = s.autorun._run_effect(run, 'analysis', 'audiovisual_analysis', 'model', [{}], 'analysis')
    assert result[0:2] == ('pause', 'provider_not_ready')
    assert 'reauth_required' in result[2]
    assert calls == ['readiness']
    assert db.conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
    assert db.conn.execute('SELECT COUNT(*) FROM reservations').fetchone()[0] == 0


def test_recovery_description_and_explicit_retry_approval(env):
    client, csrf, db, s, _ = env
    aid, event, _ = failed_attempt(db)
    db.conn.execute("UPDATE jobs SET status='failed',blocked_reason='malformed_analysis' WHERE id='invalid-job'")
    run = AutoRun(schema_version='autorun.v1', id='inspect-recovery', seed_id='seed',
        status='paused', stage='video_analysis', params={'budget_ids':[]},
        state={'analysis_jobs':['invalid-job']}, pause={'code':'analysis_failed'})
    s.autorun._put(run)
    descriptor = client.get('/api/autoruns/inspect-recovery').json()['run']['recovery']
    assert descriptor['kind'] == 'response_invalid' and descriptor['event_seq'] == event
    assert descriptor['estimate'] == {'usd_micros':250000}
    assert descriptor['can_resume'] is False
    body = {'reviewer':'operator', 'evidence':'Reviewed returned invalid response', 'event_seq':event}
    path = f'/api/attempts/{aid}/reconcile-invalid-analysis'
    assert mut(client, csrf, 'post', path, key='settle-once', json=body).status_code == 200
    count = db.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    assert mut(client, csrf, 'post', path, key='settle-after-restart', json=body).status_code == 200
    assert db.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0] == count
    response = mut(client, csrf, 'post', '/api/autoruns/inspect-recovery/resume', key='unapproved-retry', json={})
    assert response.status_code == 400 and response.json()['error'] == 'paid_analysis_retry_approval_required'
    stale = mut(client, csrf, 'post', '/api/autoruns/inspect-recovery/resume', key='stale-retry',
        json={'approve_paid_analysis_retry':True, 'reviewer':'operator',
              'analysis_attempt_id':aid, 'analysis_event_seq':event+1})
    assert stale.status_code == 400 and stale.json()['error'] == 'analysis_retry_mismatch'
    response = mut(client, csrf, 'post', '/api/autoruns/inspect-recovery/resume', key='approved-retry',
        json={'approve_paid_analysis_retry':True, 'reviewer':'operator',
              'analysis_attempt_id':aid, 'analysis_event_seq':event})
    assert response.status_code == 200
    assert db.conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1
    approval = next(p for p in s.autorun.get(run.id).progress if p['outcome'] == 'paid_retry_approved')
    assert approval['reviewer'] == 'operator' and approval['attempt_id'] == aid
    assert approval['validation_event_seq'] == event


def test_scene_cards_show_uncertainty_without_inventing_speech(env, monkeypatch):
    from modules.factory.autorun.review import blueprint_review_cards
    from modules.factory.domain.clocks import FPS_30, FrameInterval
    _, _, _, s, _ = env
    bp = SimpleNamespace(id='bp', content_hash='current', clock=FPS_30,
        speech={'transcript':[]}, beats=[SimpleNamespace(id='b2',
            target=FrameInterval(30,90), visual_event='A personal announcement',
            role='product_reveal', confidence='uncertain', speech_segment_id=None,
            evidence_ids=['missing-frame'])])
    monkeypatch.setattr(s.analysis, 'get', lambda _: bp)
    monkeypatch.setattr(s.blueprints, 'flags', lambda _: [
        {'flag':'low_confidence_scene','detail':'beat b2: uncertain'},
        {'flag':'unclear_product_action','detail':'beat b2: no speech link'}])
    cards = blueprint_review_cards(s, AutoRun(seed_id='seed'))
    assert len(cards) == 1 and cards[0]['start_s'] == 1 and cards[0]['end_s'] == 3
    assert cards[0]['speech'] == '' and cards[0]['evidence_ids'] == []
    assert any('personal announcements' in r for r in cards[0]['reasons'])
    assert any('does not justify inventing narration' in r for r in cards[0]['reasons'])
    monkeypatch.setattr(s.blueprints, 'flags', lambda _: [
        {'flag':'low_confidence_scene','detail':'beat b2: uncertain'},
        {'flag':'untranscribed_speech','detail':'audio present, transcript empty'}])
    summary = s.autorun._recovery_view(AutoRun(seed_id='seed', stage='blueprint',
        status='paused', pause={'code':'blueprint_flags'}))
    assert 'review_notices' not in summary and 'review_issues' not in summary
    assert summary['recovery']['can_resume']
    assert 'removed' in summary['recovery']['message']


def test_recovery_adoption_failure_rolls_back_settlement(env, monkeypatch):
    from modules.factory.autorun.recovery import AnalysisRecovery
    _, _, db, s, _ = env
    aid, event, rid = failed_attempt(db)
    db.conn.execute("UPDATE jobs SET status='failed' WHERE id='invalid-job'")
    s.providers['audiovisual_analysis'] = SimpleNamespace(revalidate_analysis_response=lambda *a: {
        'analysis':payload(), 'evidence':{'attempt_id':aid}})
    monkeypatch.setattr(s.seeds, 'get', lambda _: SimpleNamespace(source_asset_id='art'))
    run = AutoRun(schema_version='autorun.v1', id='rollback', seed_id='seed', status='paused',
        stage='video_analysis', params={'budget_ids':[]}, state={'analysis_jobs':['invalid-job']})
    s.autorun._put(run)
    before = db.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    def fail(*args):
        raise RuntimeError('simulated adoption crash')
    monkeypatch.setattr(s.autorun, '_put', fail)
    with pytest.raises(RuntimeError, match='adoption crash'):
        AnalysisRecovery(s).recover(run.id, {'event_seq':event,'reviewer':'operator','evidence':'Checked result'})
    assert db.conn.execute('SELECT status FROM attempts WHERE id=?',(aid,)).fetchone()[0] == 'unknown'
    assert db.conn.execute('SELECT status FROM reservations WHERE id=?',(rid,)).fetchone()[0] == 'ambiguous'
    assert s.autorun.get(run.id).state == run.state
    assert db.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0] == before
