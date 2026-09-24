"""Completed capped editorial answers must recover without another paid call."""
from copy import deepcopy
import pytest
from test_factory_flashcut_response_recovery import route  # noqa: F401
from test_factory_editorial_planning import case
from modules.factory.execution.context import dispatch_context
from modules.factory.testing.fakes import ProviderError


def editorial(adapter, monkeypatch):
    inputs, _ = case()
    monkeypatch.setattr(adapter, 'prepared', lambda _: ([], {'output_tokens_bound': 32768}))
    monkeypatch.setattr(adapter, '_response_schema', lambda _: None)
    return {'task':'plan_flashcut_edits','model':adapter.model,
            'editorial_input':inputs,'editorial_binding':{'revision':1},
            'output_policy':'flashcut_output.v2'}


def test_capped_editorial_response_uses_validated_local_plan_once(route, monkeypatch):
    adapter, _, calls, reply = route
    request = editorial(adapter, monkeypatch)
    with dispatch_context({'attempt_id':'capped-editorial'}):
        out = adapter.submit(request)
        replay = adapter.submit(request)
    assert out['status'] == replay['status'] == 'succeeded'
    assert len(calls) == 1
    result = out['result']
    assert result['plan_origin'] == 'local_conservative'
    assert result['editorial_recovery']['reason'] == 'analysis_incomplete'
    assert set(result['editorial']['variants']) == set('ABCD')


@pytest.mark.parametrize('finish', ['timeout', 'SAFETY'])
def test_editorial_recovery_never_masks_unknown_or_safety_outcomes(route, monkeypatch, finish):
    adapter, _, calls, reply = route
    request = editorial(adapter, monkeypatch)
    reply['finish'] = finish
    with dispatch_context({'attempt_id':'unproven'}), pytest.raises(ProviderError):
        adapter.submit(request)
    assert len(calls) == 1
