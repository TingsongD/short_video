import pytest

from modules.factory.domain.errors import ContractError


def context():
    return {'version': 'scene.v2', 'roles': [
        {'id': 'host', 'appearance': 'Woman with curly hair'},
        {'id': 'maker', 'appearance': 'Man with short hair'}], 'scenes': [
        {'beat_id': 'b1', 'physical_scene': 'Woman points at a planet', 'cast': ['host'],
         'wardrobe': {'host': 'blue jacket'}, 'allowed_transition': 'cut to workshop',
         'source_overlays': ['Amazing planet!'], 'environmental_text': []},
        {'beat_id': 'b2', 'physical_scene': 'Man assembles a motor in workshop', 'cast': ['maker'],
         'wardrobe': {'maker': 'red apron'}, 'allowed_transition': 'new scene and presenter',
         'source_overlays': [], 'environmental_text': ['EXIT sign']} ]}


def test_scene_local_prompt_preserves_intentional_cast_changes():
    from modules.factory.creative.context import validate_context, scene_request
    c = validate_context(context(), ['b1', 'b2'])
    b = scene_request(c, 'b2', 'B', {'aspect': '9:16'})
    assert 'motor' in b['prompt'] and 'red apron' in b['prompt']
    assert 'planet' not in b['prompt'] and 'Amazing' not in b['prompt']
    assert 'same presenter' not in b['prompt'] and 'EXIT sign' in b['prompt']
    assert b['creative_context_hash'] and b['variant_identity'] == 'B'
    assert scene_request(c, 'b2', 'C', {})['prompt'] != b['prompt']


def test_context_rejects_unknown_roles_and_missing_scenes():
    from modules.factory.creative.context import validate_context
    with pytest.raises(ContractError, match='creative_context_invalid'):
        validate_context(context(), ['b1', 'b2', 'b3'])
    c = context()
    c['scenes'][1]['cast'] = ['unknown']
    with pytest.raises(ContractError, match='creative_context_invalid'):
        validate_context(c, ['b1', 'b2'])


@pytest.mark.parametrize('field,value', [('beat_id', {}), ('physical_scene', '')])
def test_malformed_scene_is_a_typed_failure(field, value):
    from modules.factory.creative.context import validate_context
    c = context()
    c['scenes'][0][field] = value
    with pytest.raises(ContractError, match='creative_context_invalid'):
        validate_context(c, ['b1', 'b2'])


def test_reference_dependencies_are_acyclic_and_variant_scoped():
    from modules.factory.creative.references import role_dependencies, conditioned_request
    c = context()
    c['scenes'][1]['cast'] = ['host', 'maker']
    graph = role_dependencies(c, 'B')
    assert graph[0]['requires'] == {} and graph[0]['establishes'] == ['host']
    assert graph[1]['requires'] == {'host': 'b1'} and graph[1]['establishes'] == ['maker']
    anchors = {'host': {'role': 'host', 'variant': 'B', 'artifact_id': 'frame1', 'sha256': 'a'*64}}
    request = conditioned_request({'prompt':'local scene'}, anchors, ['host'], 'B')
    assert request['reference_hashes'] == {'frame1':'a'*64}
    with pytest.raises(ContractError, match='reference_variant_mismatch'):
        conditioned_request({'prompt':'local scene'}, anchors, ['host'], 'C')
    anchors['host']['sha256'] = 'b'*64
    assert conditioned_request({'prompt':'local scene'}, anchors, ['host'], 'B') != request


def test_first_appearance_split_uses_independently_qualified_mode_durations():
    from modules.factory.creative.references import scene_allocations
    cap = {'durations_s':[4,8], 'mode_capabilities': {
        'text':{'durations_s':[4,8]}, 'image_ref':{'durations_s':[5,10]}}}
    split = scene_allocations(12, cap, [], ['host'])
    assert [(a['input_mode'],a['duration_s'],a['covers_s']) for a in split] == [('text',8,8),('image_ref',5,4)]


@pytest.mark.parametrize('variation', ['full_video', 'controlled_regions'])
def test_autorun_draft_keeps_actions_when_scene_context_only_names_locations(monkeypatch, variation):
    """Exercise the draft boundary that formerly overwrote all beat actions."""
    from types import SimpleNamespace as NS
    from modules.factory.autorun.service import AutoRunService
    from modules.factory.autorun.policies import new_policies

    actions = ['Woman opens a melon.', 'Man lifts a motor.']
    c = context()
    for scene, place in zip(c['scenes'], ['Produce department', 'Workshop']):
        scene['physical_scene'] = place
    beats = [NS(id=f'b{i+1}', role='body', visual_event=action,
                target=NS(to_dict=lambda i=i: {"start_frame": i*90, "end_frame": (i+1)*90})) for i, action in enumerate(actions)]
    bp = NS(seed_id='seed', provenance={}, analysis={}, beats=beats,
            target_frames=180, clock=NS(num=30, den=1))
    captured = {}
    svc = AutoRunService.__new__(AutoRunService)
    svc.s = NS(db=None, analysis=NS(get=lambda _: bp),
               create_experiment_draft=lambda eid, body: captured.update(body))
    monkeypatch.setattr('modules.factory.analysis.deep.bound_gate', lambda *a: None)
    monkeypatch.setattr(svc, '_generation_route', lambda _: ('vertex', 'fake'))
    monkeypatch.setattr(svc, '_generation_settings', lambda *a: {'aspect': '9:16', 'resolution': '720p'})
    monkeypatch.setattr(svc, '_advance', lambda *a: None)
    sc = {key: {'b1': 'First action', 'b2': 'Second action'} for key in 'ABCD'}
    sc.update(changed={key: 'b1' for key in 'BCD'},
              factors={key: 'hook' for key in 'BCD'},
              hypotheses={key: 'Test' for key in 'BCD'},
              metrics={key: 'retention' for key in 'BCD'})
    run = NS(id='auto-fixture', params={'workflow': 'full_video', 'voice_id': 'voice',
             'language': 'en', 'policies': new_policies({'variation': variation})},
             state={'blueprint_id': 'bp', 'template_id': 'template', 'scripts': sc,
                    'analysis': {'creative_context': c}})
    assert svc._stage_draft(run) == 'next'
    for segments in [captured['segments']] + [v['segments'] for v in captured['variants']]:
        for i, segment in enumerate(segments):
            prompt = segment['picture']['request']['prompt']
            assert actions[i] in prompt
            assert actions[1-i] not in prompt
            assert c['scenes'][i]['physical_scene'] in prompt
            assert 'Amazing planet!' not in prompt


def test_scene_action_excludes_source_overlay_directions():
    from modules.factory.creative.context import validate_context, scene_request
    c = validate_context(context(), ['b1', 'b2'])
    r = scene_request(c, 'b2', 'A', {},
                      visual_event='Man lifts the motor. Overlay reads BUY NOW.')
    assert 'Man lifts the motor.' in r['prompt']
    assert 'BUY NOW' not in r['prompt']
