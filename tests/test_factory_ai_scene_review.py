"""Retired scene gate: automatic preparation, no review calls or fake verdicts."""
import copy
import json
import pytest
from test_factory_application import application
from test_factory_autorun import stack, make_seed, launch, drive, ANALYZE
from modules.factory.domain.errors import ContractError


def prepared(application):
    observed = copy.deepcopy(ANALYZE)
    observed['beats'][1]['role'] = 'product_reveal'
    s, c, act, w, root = stack(application, analyze_result=observed)
    s.ref_analysis.hypit.boundaries = lambda src: {'boundaries': []}
    s.autorun._stage_template = lambda run: ('pause', 'test_stop', 'Reached template', '')
    calls = []
    adapter = s.providers['audiovisual_analysis']
    original = adapter.transport
    def transport(method, url, data, headers):
        calls.append(json.loads(data))
        return original(method, url, data, headers)
    adapter.transport = transport
    run = launch(act, make_seed(act, root), ai_scene_review=True,
                 generate_music=False, visual_reviews=False)
    drive(s, w)
    return s, c, act, w, run['id'], calls


def test_flagged_scenes_continue_without_review_or_false_approval(application):
    s, c, act, w, rid, calls = prepared(application)
    run = c.get('/api/autoruns/' + rid).json()['run']
    assert run['stage'] == 'template', run.get('pause')
    assert run['pause']['code'] == 'test_stop'
    assert 'ai_scene_review' not in run and 'review_issues' not in run
    assert 'ai_scene_review' not in run['params']
    bp = s.analysis.get(run['state']['blueprint_id'])
    assert bp.status == 'accepted'
    assert bp.beats[1].confidence != 'reviewed'
    assert s.blueprints.flags(bp.id), 'Content uncertainty must not be erased'
    assert bp.provenance['review_performed'] is False
    assert len(calls) == 1, 'Only initial analysis; no paid scene review'
    events = s.db.conn.execute("SELECT body FROM events WHERE type='prepared_without_scene_review'").fetchall()
    assert events and json.loads(events[0][0])['review_performed'] is False


@pytest.mark.parametrize('unknown', [False, True])
def test_legacy_scene_pause_resumes_only_when_paid_outcomes_are_known(application, unknown):
    s, c, act, w, rid, calls = prepared(application)
    run = s.autorun.get(rid)
    attempt = s.db.conn.execute('SELECT id,job_id FROM attempts LIMIT 1').fetchone()
    run.stage = 'blueprint'
    run.pause = {'code': 'ai_scene_review_unresolved', 'at': 'legacy-pause', 'detail': 'Old disagreement'}
    run.state['scene_review_correct_jobs'] = [attempt['job_id']]
    run.state['scene_review'] = {'status': 'stopped'}
    s.autorun._put(run)
    if unknown:
        s.db.conn.execute("UPDATE attempts SET status='unknown' WHERE id=?", (attempt['id'],))
    before = s.db.conn.execute('SELECT count(*) FROM attempts').fetchone()[0]
    view = c.get('/api/autoruns/' + rid).json()['run']
    assert view['recovery']['can_resume'] is not unknown
    assert 'ai_scene_review' not in view
    result = act('post', '/api/autoruns/' + rid + '/resume', {})
    if unknown:
        assert result.status_code == 400
        assert result.json()['error'] == 'analysis_reconciliation_required'
    else:
        assert result.status_code == 200
        drive(s, w)
        assert s.autorun.get(rid).stage == 'template'
    assert s.db.conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == before
    assert len(calls) == 1


@pytest.mark.parametrize('action', ['proceed_anyways', 'use_manual_fix', 'replace_unknown_once', 'replace_incomplete_once'])
def test_removed_review_actions_cannot_dispatch_or_approve(application, action):
    s, c, act, w, rid, calls = prepared(application)
    response = act('post', '/api/autoruns/' + rid + '/resume', {'scene_review_action': action})
    assert response.status_code == 400
    assert response.json()['error'] == 'scene_review_removed'
    assert len(calls) == 1


def test_removed_review_does_not_allow_changed_source(application):
    s, c, act, w, rid, calls = prepared(application)
    run = s.autorun.get(rid)
    run.stage = 'blueprint'
    run.state['analysis_source_sha'] = 'different-source'
    s.autorun._put(run)
    assert act('post', '/api/autoruns/' + rid + '/resume', {}).status_code == 200
    drive(s, w)
    assert s.autorun.get(rid).pause['code'] == 'analysis_source_changed'
    assert len(calls) == 1


@pytest.mark.parametrize('bad', ['stale_hash', 'timing_gap'])
def test_automatic_preparation_preserves_structural_guards(application, bad):
    s, c, act, w, rid, calls = prepared(application)
    bp = s.analysis.get(s.autorun.get(rid).state['blueprint_id'])
    if bad == 'timing_gap':
        beats = bp.to_dict()['beats']
        beats[1]['target']['start_frame'] += 1
        s.blueprints._update(bp.id, beats=beats, status='draft')
    count = s.db.conn.execute("SELECT count(*) FROM events WHERE type='prepared_without_scene_review'").fetchone()[0]
    with pytest.raises(ContractError):
        s.blueprints.prepare_automatically(bp.id, 'stale' if bad == 'stale_hash' else bp.content_hash)
    assert s.db.conn.execute("SELECT count(*) FROM events WHERE type='prepared_without_scene_review'").fetchone()[0] == count
