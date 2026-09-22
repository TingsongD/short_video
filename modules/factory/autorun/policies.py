"""Versioned future-run policy validation; absent policies mean legacy behavior.

Pure helpers only. Defaults are applied at creation, never when loading an
existing run. Callers must persist returned policies before dispatching work.
"""
from copy import deepcopy

from ..domain.errors import ContractError


LEGACY = {
    'version': 1, 'variation': 'controlled_regions', 'captions': 'words.v1',
    'delivery': 'creative_approval', 'speech_repairs': 0, 'overlay_repairs': 0,
}

DEFAULT_RUN_USD_CAP_MICROS = 50_000_000


def new_policies(value=None, *, authorized_destination=False):
    defaults = {
        'version': 1, 'variation': 'full_video', 'captions': 'phrases.v1',
        'delivery': 'after_qc' if authorized_destination else 'creative_approval',
        'speech_repairs': 2, 'overlay_repairs': 2,
    }
    if value is not None and not isinstance(value, dict):
        raise ContractError('invalid_run_policy', 'policies')
    if set(value or {}) - set(defaults):
        raise ContractError('invalid_run_policy', 'policies', 'unknown policy field')
    defaults.update(value or {})
    return validate_policies(defaults)


def validate_policies(value):
    if not isinstance(value, dict) or set(value) != set(LEGACY):
        raise ContractError('invalid_run_policy', 'policies', 'incomplete policy')
    choices = {'variation': ('controlled_regions', 'full_video'),
               'captions': ('words.v1', 'phrases.v1'),
               'delivery': ('creative_approval', 'after_qc')}
    if type(value['version']) is not int or value['version'] != 1:
        raise ContractError('unsupported_run_policy', 'version')
    for key, allowed in choices.items():
        if value[key] not in allowed:
            raise ContractError('invalid_run_policy', key)
    for key in ('speech_repairs', 'overlay_repairs'):
        if type(value[key]) is not int or not 0 <= value[key] <= 2:
            raise ContractError('invalid_run_policy', key, 'must be between zero and two')
    return deepcopy(value)


def run_policies(params):
    """Do not apply new defaults to records created before this feature."""
    if 'policies' not in params:
        return deepcopy(LEGACY)
    return validate_policies(params['policies'])


def new_spending_policy(run_id):
    """Server-issued cumulative USD authority for one new run.

    The budget identity is derived from the run identity so it cannot be
    selected as reusable funding by another run. Existing records without
    this policy retain their saved behavior.
    """
    if not isinstance(run_id, str) or not run_id.startswith('auto-'):
        raise ContractError('invalid_run_id', 'run_id')
    return {
        'version': 1,
        'scope': 'cumulative_run',
        'unit': 'usd_micros',
        'cap_amount': DEFAULT_RUN_USD_CAP_MICROS,
        'budget_id': f'run_guardrail:{run_id}:usd',
    }


def run_spending_policy(params):
    """Return a validated saved policy; never retrofit legacy runs."""
    value = params.get('spending_policy')
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
            'version', 'scope', 'unit', 'cap_amount', 'budget_id'}:
        raise ContractError('invalid_spending_policy', 'spending_policy')
    if (value['version'] != 1 or value['scope'] != 'cumulative_run'
            or value['unit'] != 'usd_micros'
            or value['cap_amount'] != DEFAULT_RUN_USD_CAP_MICROS
            or not isinstance(value['budget_id'], str)
            or not value['budget_id'].startswith('run_guardrail:auto-')
            or not value['budget_id'].endswith(':usd')):
        raise ContractError('invalid_spending_policy', 'spending_policy')
    return deepcopy(value)
