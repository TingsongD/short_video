"""Scene-local intent. Cast continuity applies to roles, not to the whole film."""
import copy
import re

from ..domain.errors import ContractError
from ..domain.records import content_hash

VERSION = 'scene.v2'
LOOKS = {
    'A': 'Natural observational framing and faithful scene action.',
    'B': 'Close immersive handheld camera, warm daylight, expressive reactions.',
    'C': 'Steady medium-wide camera, cool daylight, clear step-by-step action.',
    'D': 'Low-angle cinematic tracking, golden-hour light, playful anticipation.',
}


def validate_context(value, beat_ids):
    def invalid(field):
        raise ContractError('creative_context_invalid', field, 'Scene and recurring-role evidence must match this source.')
    if not isinstance(value, dict) or value.get('version') != VERSION:
        invalid('version')
    roles, scenes = value.get('roles'), value.get('scenes')
    if not isinstance(roles, list) or not isinstance(scenes, list):
        invalid('roles/scenes')
    ids = []
    for role in roles:
        if not isinstance(role, dict) or any(not isinstance(role.get(k), str) or not role[k].strip() for k in ('id', 'appearance')):
            invalid('role')
        ids.append(role['id'])
    if len(ids) != len(set(ids)):
        invalid('duplicate_role')
    scene_ids = []
    for scene in scenes:
        if not isinstance(scene, dict):
            invalid('scene')
        if not isinstance(scene.get('beat_id'), str) or not scene['beat_id'].strip():
            invalid('beat_id')
        scene_ids.append(scene.get('beat_id'))
        for field in ('physical_scene', 'allowed_transition'):
            if not isinstance(scene.get(field), str):
                invalid(field)
        if not scene['physical_scene'].strip():
            invalid('physical_scene')
        for field in ('cast', 'source_overlays', 'environmental_text'):
            if not isinstance(scene.get(field), list) or any(not isinstance(v, str) for v in scene[field]):
                invalid(field)
        if len(scene['cast']) != len(set(scene['cast'])) or not set(scene['cast']).issubset(ids):
            invalid('cast')
        wardrobe = scene.get('wardrobe')
        if not isinstance(wardrobe, dict) or not set(wardrobe).issubset(scene['cast']) or any(not isinstance(v, str) for v in wardrobe.values()):
            invalid('wardrobe')
    if len(scene_ids) != len(set(scene_ids)) or set(scene_ids) != set(beat_ids):
        invalid('scene_bindings')
    result = copy.deepcopy(value)
    result.pop('content_hash', None)
    result['content_hash'] = content_hash(result)
    return result


def from_analysis(analysis, beats):
    """Legacy/fake observations do not invent role identities or certify them."""
    supplied = analysis.get('creative_context')
    if supplied is not None:
        return validate_context(supplied, [b.id for b in beats])
    scenes = []
    for beat in beats:
        # Overlay clauses from old observations are not physical directions.
        clauses = re.split(r'(?<=[.;])\s+|\n', str(beat.visual_event))
        overlay = [s for s in clauses if re.search(r'\b(caption|subtitle|watermark|overlay|on-screen text)\b', s, re.I)]
        scenes.append({'beat_id': beat.id, 'physical_scene': ' '.join(s for s in clauses if s not in overlay),
            'cast': [], 'wardrobe': {}, 'allowed_transition': 'Unresolved; do not assume a shared presenter.',
            'source_overlays': overlay, 'environmental_text': []})
    return validate_context({'version': VERSION, 'roles': [], 'scenes': scenes, 'evidence_quality': 'roles_unavailable'}, [b.id for b in beats])


def scene_request(context, beat_id, variant, settings):
    scene = next((s for s in context['scenes'] if s['beat_id'] == beat_id), None)
    if scene is None or variant not in LOOKS:
        raise ContractError('creative_context_invalid', 'scene/variant')
    cast = [r['id'] + ': ' + r['appearance'] + '; wardrobe: ' + scene['wardrobe'].get(r['id'], 'unspecified')
            for r in context['roles'] if r['id'] in scene['cast']]
    prompt = ('Vertical 9:16 original fictional or authorized social footage. This clip depicts ONLY: '
        + scene['physical_scene'] + '. Cast for THIS scene: ' + (' | '.join(cast) or 'No verified recurring role; follow this scene alone.')
        + ' Intentional transition: ' + scene['allowed_transition'] + '. ' + LOOKS[variant]
        + ' Keep each recurring role consistent with its own references, allowing the declared wardrobe and scene changes.'
        + ' No superimposed subtitles, captions, title cards, decorative lettering, logos or watermarks. Captions are added later.')
    if scene['environmental_text']:
        prompt += ' Physical environmental text may remain: ' + '; '.join(scene['environmental_text'])
    return {'kind': 'video', 'mode': 't2v', 'prompt': prompt, 'settings': dict(settings),
        'workflow_version': 2, 'prompt_policy': VERSION, 'creative_context_hash': context['content_hash'],
        'scene_id': beat_id, 'cast_roles': list(scene['cast']), 'variant_identity': variant}


def qc_intent(context, segments, fps):
    by_id = {s['beat_id']: s for s in context['scenes']}
    return {'policy': 'visual.v2', 'creative_context': context,
        'scenes': [{**copy.deepcopy(by_id[s['id']]), 'start_s': s['target']['start_frame'] / fps,
                    'end_s': s['target']['end_frame'] / fps} for s in segments]}
