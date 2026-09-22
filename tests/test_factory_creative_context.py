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
