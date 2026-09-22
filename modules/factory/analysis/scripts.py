"""Validate provider script structure before draft creation or paid speech."""
from ..domain.errors import ContractError


def validate_script_response(response, beat_ids, changed):
    def reject(field):
        raise ContractError('invalid_script_response', field,
                            'Expected complete A/B/C/D string copy bound to known beats.')
    if not isinstance(response, dict) or not isinstance(response.get('variants'), dict):
        reject('variants')
    variants = response['variants']
    if set(variants) != set('ABCD'):
        reject('variants')
    known = set(beat_ids)
    for key in 'ABCD':
        value = variants[key]
        if not isinstance(value, dict) or set(value) - known:
            reject('variants.' + key)
        required = known if key == 'A' else {changed[key]} if key in changed else known
        if not required <= set(value) or any(not isinstance(text, str) for text in value.values()):
            reject('variants.' + key)
    hypotheses = response.get('hypotheses', {})
    if not isinstance(hypotheses, dict) or set(hypotheses) - set('BCD') or any(
            not isinstance(value, str) for value in hypotheses.values()):
        reject('hypotheses')
    return response
