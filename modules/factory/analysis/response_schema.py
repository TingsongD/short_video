"""Provider-only output constraint. Frozen domain contracts stay unchanged.

The schema controls shape, not truth: temporal/semantic validation is mandatory.
Only the conservative subset supported by Vertex responseSchema is used.
"""


def object_schema(properties):
    return {'type': 'OBJECT', 'properties': properties, 'required': list(properties)}


TEXT = {'type': 'STRING'}
NUMBER = {'type': 'NUMBER', 'minimum': 0}
WORDS = {'type': 'ARRAY', 'items': object_schema({
    'text': TEXT, 'start_s': NUMBER, 'end_s': NUMBER}), 'maxItems': 0}
ANALYSIS_SCHEMA = object_schema({
    'beats': {'type': 'ARRAY', 'minItems': 1, 'items': object_schema({
        'id': TEXT, 'start_s': NUMBER, 'end_s': NUMBER,
        'role': {'type': 'STRING', 'enum': ['hook', 'product_reveal', 'proof', 'payoff', 'cta', 'transition', 'body']},
        'confidence': {'type': 'STRING', 'enum': ['uncertain', 'unresolved']},
        'visual_event': TEXT})},
    'transcript': {'type': 'ARRAY', 'items': object_schema({
        'id': TEXT, 'start_s': NUMBER, 'end_s': NUMBER, 'text': TEXT, 'words': WORDS})},
    'music': object_schema({'role': TEXT}),
    'uncertainty': {'type': 'ARRAY', 'items': TEXT}})

# Provider-only sidecar; the frozen blueprint schema is intentionally unchanged.
CREATIVE_CONTEXT_SCHEMA = object_schema({
    'version': {'type': 'STRING', 'enum': ['scene.v2']},
    'roles': {'type': 'ARRAY', 'items': object_schema({'id': TEXT, 'appearance': TEXT})},
    'scenes': {'type': 'ARRAY', 'items': object_schema({
        'beat_id': TEXT, 'physical_scene': TEXT, 'cast': {'type': 'ARRAY', 'items': TEXT},
        'wardrobe': {'type': 'ARRAY', 'items': object_schema({'role': TEXT, 'description': TEXT})},
        'allowed_transition': TEXT, 'source_overlays': {'type': 'ARRAY', 'items': TEXT},
        'environmental_text': {'type': 'ARRAY', 'items': TEXT}})}})


def scene_analysis_schema():
    import copy
    schema = copy.deepcopy(ANALYSIS_SCHEMA)
    schema['properties']['creative_context'] = CREATIVE_CONTEXT_SCHEMA
    schema['required'].append('creative_context')
    return schema
