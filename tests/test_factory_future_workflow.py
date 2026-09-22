"""Future-run policies through the API; all external transports are fixtures."""
from test_factory_autorun import application, stack, make_seed, launch, drive
from modules.factory.autorun.policies import new_policies
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import pytest


def test_speech_repairs_are_bounded_and_survive_service_restart(application):
    from modules.factory.autorun.service import AutoRunService
    s, c, act, w, root = stack(application)
    analysis = s.providers['audiovisual_analysis']
    original = analysis.transport
    prompts = []
    def transport(method, url, body, headers):
        payload = json.loads(body)
        text = str(payload['contents'][0]['parts'])
        if 'SHORTEN_SPEECH_V1' in text:
            prompts.append(text)
            result = {'text': 'Observe.' if len(prompts) == 1 else 'Look!',
                      'meaning_preserved': True, 'hypothesis_preserved': True, 'complete': True}
            return 200, {}, json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(result)}]}}]}).encode()
        return original(method, url, body, headers)
    analysis.transport = transport
    tts = s.providers['elevenlabs'].impl
    submit = tts.submit
    def slow(request):
        out = submit(request)
        if request['text'] in ('watch this dog now', 'Observe.', 'Look!'):
            tts.doc['ops'][out['operation_id']]['duration_s'] = 6.0
        tts._save()
        return out
    tts.submit = slow
    run = launch(act, make_seed(act, root), policies=new_policies(), generate_music=False)
    drive(s, w)
    state = s.autorun.get(run['id'])
    assert state.pause['code'] == 'speech_repair_exhausted', state.pause
    assert len(prompts) == 2
    assert '6.0' in prompts[0] and 'beat_duration_s' in prompts[0]
    assert state.state['speech_repair_attempts']['A:b0'] == 2
    # Only the affected narration is repurchased. All other lines keep
    # their original provider operation despite both draft revisions.
    utterances = [op['request']['text'] for op in json.loads((root / 'tts.json').read_text())['ops'].values()]
    assert len(utterances) == 8
    assert len(set(utterances)) == 8
    s.autorun = AutoRunService(s)
    response = act('post', f'/api/autoruns/{run["id"]}/resume', {})
    assert response.status_code in (200, 202), response.text
    drive(s, w)
    assert len(prompts) == 2


def test_unusable_completed_rewrite_uses_the_second_bounded_attempt(application):
    s, _client, act, worker, root = stack(application)
    analysis = s.providers['audiovisual_analysis']
    original = analysis.transport
    prompts = []

    def transport(method, url, body, headers):
        payload = json.loads(body)
        text = str(payload['contents'][0]['parts'])
        if 'SHORTEN_SPEECH_V1' in text:
            prompts.append(text)
            result = ({'text': '', 'meaning_preserved': False,
                       'hypothesis_preserved': False, 'complete': False}
                      if len(prompts) == 1 else
                      {'text': 'Watch.', 'meaning_preserved': True,
                       'hypothesis_preserved': True, 'complete': True})
            return 200, {}, json.dumps({'candidates': [{'finishReason': 'STOP',
                'content': {'parts': [{'text': json.dumps(result)}]}}]}).encode()
        return original(method, url, body, headers)

    analysis.transport = transport
    tts = s.providers['elevenlabs'].impl
    submit = tts.submit

    def slow_original(request):
        result = submit(request)
        if request['text'] == 'watch this dog now':
            tts.doc['ops'][result['operation_id']]['duration_s'] = 6.0
            tts._save()
        return result

    tts.submit = slow_original
    run = launch(act, make_seed(act, root), policies=new_policies(),
                 generate_music=False)
    for _ in range(500):
        result = worker.tick()
        current = s.autorun.get(run['id'])
        if current.state.get('tts_done'):
            break
        if result is None:
            future = s.scheduler.clock() + timedelta(seconds=5)
            s.scheduler.clock = lambda: future
    assert current.status == 'running', (current.stage, current.pause)
    assert current.state.get('tts_done') is True
    assert len(prompts) == 2
    assert current.state['speech_repair_attempts']['A:b0'] == 2
    assert current.state['speech_repair_rejections'][0]['attempt'] == 1
    assert 'Cannot verify' in current.state['speech_repair_rejections'][0]['reason']


def distinct_transport(s):
    """The provider fixture must return distinct bytes for distinct prompts."""
    from modules.factory.testing.fixtures import _moving_mp4
    for provider in ('jimeng_canvas', 'google_vertex'):
        adapter = s.providers.get(provider)
        if not adapter or not hasattr(adapter, 'remote'):
            continue
        original = adapter.download
        def download(oid, destination=None, adapter=adapter, original=original):
            row = adapter.poll(oid)
            path = adapter.remote / (oid + '.mp4')
            if not path.exists():
                color = '0x' + hashlib.sha256(json.dumps(row['request'], sort_keys=True).encode()).hexdigest()[:6]
                _moving_mp4(path, row['request']['duration_s'], size='180x320', color=color)
            return original(oid, destination)
        adapter.download = download
    overlay_transport(s)


@pytest.mark.parametrize('failure', ['budget', 'unknown'])
def test_paid_speech_repair_refuses_budget_or_unknown_replay(application, failure):
    s, c, act, w, root = stack(application)
    adapter = s.providers['audiovisual_analysis']
    original_price, original_transport = adapter.price, adapter.transport
    submissions = []
    def price(request):
        result = original_price(request)
        if request.get('task') == 'shorten_speech' and failure == 'budget':
            result.update(amount=501, reserve_amount=501)
        return result
    def transport(method, url, body, headers):
        if 'SHORTEN_SPEECH_V1' in str(json.loads(body)['contents'][0]['parts']):
            submissions.append(body)
            raise TimeoutError('Fixture: response lost after request submission')
        return original_transport(method, url, body, headers)
    adapter.price, adapter.transport = price, transport
    tts = s.providers['elevenlabs'].impl
    submit = tts.submit
    def slow(request):
        result = submit(request)
        if request['text'] == 'watch this dog now':
            tts.doc['ops'][result['operation_id']]['duration_s'] = 6.0
            tts._save()
        return result
    tts.submit = slow
    run = launch(act, make_seed(act, root), policies=new_policies(), generate_music=False)
    drive(s, w)
    current = s.autorun.get(run['id'])
    assert current.status == 'paused'
    assert current.pause['code'] == ('budget_exhausted' if failure == 'budget' else 'repair_outcome_unknown'), current.pause
    assert len(submissions) == (0 if failure == 'budget' else 1)
    assert current.state['speech_repair_attempts']['A:b0'] == 1
    resumed = act('post', f'/api/autoruns/{run["id"]}/resume', {})
    assert resumed.status_code in (200, 202), resumed.text
    drive(s, w)
    assert len(submissions) == (0 if failure == 'budget' else 1)
    assert s.autorun.get(run['id']).state['speech_repair_attempts']['A:b0'] == 1


def overlay_transport(s, verdict='pass', overlay='none'):
    adapter = s.providers['audiovisual_analysis']
    original = adapter.transport
    def transport(method, url, body, headers):
        if 'OVERLAY_QC_V1' in str(json.loads(body)['contents'][0]['parts']):
            result = {'verdict': verdict, 'overlay': overlay, 'notes': ['0.5s: observed overlay state']}
            return 200, {}, json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(result)}]}}]}).encode()
        return original(method, url, body, headers)
    adapter.transport = transport


@pytest.mark.parametrize('verdict,overlay,expected,repairs', [
    ('fail', 'unwanted', 'overlay_repair_exhausted', 2),
    ('uncertain', 'uncertain', 'overlay_qc_uncertain', 0),
    ('fail', 'unwanted', 'overlay_repair_exhausted', 0),
])
def test_overlay_evidence_controls_bounded_regeneration(application, verdict, overlay, expected, repairs):
    s, c, act, w, root = stack(application)
    distinct_transport(s)
    overlay_transport(s, verdict, overlay)
    policies = new_policies({'overlay_repairs': 0}) if expected == 'overlay_repair_exhausted' and repairs == 0 else new_policies()
    run = launch(act, make_seed(act, root), policies=policies, generate_music=False)
    drive(s, w)
    current = s.autorun.get(run['id'])
    assert current.status == 'paused'
    assert current.pause['code'] == expected, current.pause
    assert sum(current.state.get('overlay_repair_attempts', {}).values()) == repairs
    plans = [json.loads(r[0]) for r in s.db.conn.execute("SELECT body FROM records WHERE kind='effectplan' AND json_extract(body,'$.kind')='generation'")]
    assert len(plans) == repairs
    assert all(p['total'] for p in plans)
    assert not s.db.conn.execute("SELECT id FROM records WHERE kind='renderbuild'").fetchall()


def test_explicit_future_policy_is_persisted_without_changing_legacy_runs(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    legacy = launch(act, seed)
    requested = new_policies()
    future = launch(act, seed, policies=requested)
    assert s.autorun.get(future['id']).params['policies'] == requested
    assert 'policies' not in s.autorun.get(legacy['id']).params


def test_full_video_draft_has_distinct_every_beat_requests_and_frozen_policy(application):
    s, c, act, w, root = stack(application)
    run = launch(act, make_seed(act, root), policies=new_policies(), generate_music=False)
    for _ in range(300):
        state = s.autorun.get(run['id'])
        if state.experiment_id or state.status == 'paused':
            break
        if w.tick() is None:
            future = s.scheduler.clock() + timedelta(seconds=5)
            s.scheduler.clock = lambda: future
    assert state.experiment_id, state.pause
    result = s.experiment_results(state.experiment_id)
    variants = result['variants']
    assert len(variants) == 4
    requests = [seg['picture']['request'] for v in variants for seg in v['segments']]
    import json
    assert len({json.dumps(req, sort_keys=True) for req in requests}) == 12
    assert all('no superimposed subtitles' in req['prompt'].lower() for req in requests)
    assert all(req['prompt_policy'] == 'scene.v2' for req in requests)
    assert all('multi-variable' in v['changes']['summary'] for v in variants if v['variant_key'] != 'A')
    assert all('full-video footage' in v['changes']['label'] for v in variants if v['variant_key'] != 'A')


def test_full_video_and_phrase_captions_complete_through_real_worker(application):
    s, c, act, w, root = stack(application)
    distinct_transport(s)
    overlay_transport(s, 'pass', 'incidental')
    run = launch(act, make_seed(act, root), policies=new_policies(), generate_music=False)
    drive(s, w)
    current = s.autorun.get(run['id'])
    assert current.status == 'succeeded', (current.stage, current.pause)
    result = s.experiment_results(current.experiment_id)
    plan = s.plan_for(current.experiment_id)
    pictures = [n for n in s.production._nodes(plan['id']).values() if n['kind'] == 'picture']
    assert len(pictures) == 12 and all(len(n['consumers']) == 1 for n in pictures)
    assert plan['total_price']['jimeng_credits'] == sum(n['price']['amount'] for n in pictures)
    assert len([v for v in result['variants'] if v.get('final')]) == 4
    for v in result['variants']:
        assert all(c['verdict'] == 'pass' for c in v['checks'])
        assert any(len(cap['text'].split()) > 1 for seg in v['segments'] for cap in seg['captions'])


def test_full_video_rejects_cross_variant_provider_bytes(application):
    s, c, act, w, root = stack(application)
    # Intentionally leave the generation fixture's identical returned bytes.
    overlay_transport(s)
    run = launch(act, make_seed(act, root), policies=new_policies(), generate_music=False)
    drive(s, w)
    current = s.autorun.get(run['id'])
    assert current.status == 'paused'
    assert 'cross_variant_footage_reuse' in str(current.pause), current.pause


def test_one_confirmed_overlay_repairs_only_that_clip_then_completes(application):
    s, c, act, w, root = stack(application)
    distinct_transport(s)
    adapter = s.providers['audiovisual_analysis']
    original = adapter.transport
    reviews = []
    def transport(method, url, body, headers):
        if 'OVERLAY_QC_V1' in str(json.loads(body)['contents'][0]['parts']):
            reviews.append(body)
            if len(reviews) == 1:
                result = {'verdict': 'fail', 'overlay': 'unwanted', 'notes': ['0.5s: superimposed title across subject']}
                return 200, {}, json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(result)}]}}]}).encode()
        return original(method, url, body, headers)
    adapter.transport = transport
    run = launch(act, make_seed(act, root), policies=new_policies(), generate_music=False)
    drive(s, w)
    current = s.autorun.get(run['id'])
    assert current.status == 'succeeded', current.pause
    assert sum(current.state['overlay_repair_attempts'].values()) == 1
    assert len(reviews) == 13  # 12 original clips + exactly one replacement.
    assert s.db.conn.execute("SELECT count(*) FROM events WHERE type='overlay_clip_replaced'").fetchone()[0] == 1


def test_automatic_delivery_is_verified_without_human_creative_approval(application):
    s, c, act, w, root = stack(application)
    distinct_transport(s)
    run = launch(act, make_seed(act, root), policies=new_policies(authorized_destination=True), generate_music=False)
    drive(s, w)
    current = s.autorun.get(run['id'])
    assert current.status == 'succeeded', (current.stage, current.pause)
    assert current.state['completion_phases']['delivery'] == 'complete'
    deliveries = s.db.conn.execute("SELECT body FROM records WHERE kind='delivery'").fetchall()
    assert len(deliveries) == 4
    assert all(json.loads(d[0])['status'] == 'verified' for d in deliveries)
    assert not s.db.conn.execute("SELECT id FROM records WHERE kind='review' AND json_extract(body,'$.check_type')='creative'").fetchall()
    assert not s.db.conn.execute("SELECT id FROM records WHERE kind='publication'").fetchall()
    # A pending/failing recheck immediately supersedes the earlier pass.
    final = s.experiment_results(current.experiment_id)['variants'][0]['final']
    path = s.artifacts.verified_path(final['artifact_id'])
    binding = final['binding']
    scope = s.quality.visual_scope(binding)
    old_checks = [r['id'] for r in s._final_checks(final)]
    s.quality.begin_visual(binding, scope, 'explicit-recheck')
    from modules.factory.domain.errors import ContractError
    with pytest.raises(ContractError, match='visual_qc_pending'):
        s.quality.accept(path,old_checks,binding,automated_delivery=True)
    s.quality.complete_visual(binding,scope,'explicit-recheck','fail', review_evidence={'issues':[{'start_s':0,'end_s':1,'observation':'Drift'}]})
    checks = [r['id'] for r in s._final_checks(final)]
    with pytest.raises(ContractError, match='automated_visual:fail'):
        s.quality.accept(path,checks,binding,automated_delivery=True)
    s.quality.begin_visual(binding,scope,'corrected-recheck')
    s.quality.complete_visual(binding,scope,'corrected-recheck','pass')
    checks = [r['id'] for r in s._final_checks(final)]
    assert s.quality.accept(path,checks,binding,automated_delivery=True)['accepted']
    # A changed configured account must not use a verified-result shortcut.
    s.delivery.drive.expected_account = 'other-account'
    result = act('post',f'/api/variants/{current.experiment_id}:a/deliver', {
        'artifact_id':final['artifact_id'],'target_hash':final['sha256'],'folder_id':'folder',
        'account':'fixture-drive','reviewer':'qa','valid_until':current.params['valid_until'],
        'check_ids':checks},rev=current.state['experiment_revision'])
    assert result.status_code == 400 and result.json()['error'] == 'delivery_account_changed', result.text
