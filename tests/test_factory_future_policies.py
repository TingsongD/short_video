import pytest

from modules.factory.autorun.policies import new_policies, run_policies
from modules.factory.budget import BudgetService, ReservationBlocked
from modules.factory.domain.errors import ContractError
from test_factory_application import application  # noqa: F401
from test_factory_autorun import stack, make_seed, launch


def test_new_defaults_and_destination():
    p = new_policies()
    assert p['variation'] == 'full_video'
    assert p['captions'] == 'phrases.v1'
    assert p['speech_repairs'] == p['overlay_repairs'] == 2
    assert p['delivery'] == 'creative_approval'
    assert new_policies(authorized_destination=True)['delivery'] == 'after_qc'


def test_legacy_load_is_unchanged_and_isolated():
    params = {'voice_id': 'existing'}
    p = run_policies(params)
    assert p['variation'] == 'controlled_regions'
    assert p['captions'] == 'words.v1'
    assert p['delivery'] == 'creative_approval'
    p['variation'] = 'full_video'
    assert run_policies(params)['variation'] == 'controlled_regions'
    assert params == {'voice_id': 'existing'}


@pytest.mark.parametrize('value', [[], {'version': 2}, {'version': True},
    {'speech_repairs': 3}, {'overlay_repairs': -1}, {'speech_repairs': True},
    {'variation': 'anything'}, {'captions': 'unknown'}, {'extra': 'value'}])
def test_invalid_policy_rejected(value):
    with pytest.raises(ContractError):
        new_policies(value)


def test_explicit_policies_are_copied_not_silently_defaulted():
    p = new_policies({'variation': 'controlled_regions'})
    loaded = run_policies({'policies': p})
    assert loaded == p and loaded is not p
    with pytest.raises(ContractError):
        run_policies({'policies': {'version': 1}})


def test_new_run_gets_an_isolated_cumulative_fifty_dollar_guardrail(application):
    s, _client, act, _worker, root = stack(application)
    run = launch(act, make_seed(act, root),
                 budget_ids=['credits-gen', 'credits-tts'])

    policy = run['params']['spending_policy']
    assert policy == {
        'version': 1,
        'scope': 'cumulative_run',
        'unit': 'usd_micros',
        'cap_amount': 50_000_000,
        'budget_id': f"run_guardrail:{run['id']}:usd",
    }
    assert policy['budget_id'] in run['params']['budget_ids']
    budget = s.db.conn.execute(
        'SELECT unit,scope,scope_key,cap_amount FROM budgets WHERE id=?',
        (policy['budget_id'],)).fetchone()
    assert dict(budget) == {
        'unit': 'usd_micros', 'scope': 'experiment',
        'scope_key': run['id'], 'cap_amount': 50_000_000,
    }
    assert BudgetService(s.db).selection_info(policy['budget_id']) == {
        'classification': 'run_guardrail',
        'selection_eligible': False,
        'retired': False,
    }
    status = s.autorun.detail(run['id'])['spending_policy']
    assert status['cap_amount'] == status['remaining'] == 50_000_000
    assert status['committed'] == 0
    # The run guardrail does not weaken stricter applicable shared ceilings.
    BudgetService(s.db).create_budget(
        'credits-usd', 'usd_micros', 'aggregate', cap=100_000_000)
    loaded = s.autorun.get(run['id'])
    assert s.autorun._cover(loaded, {'usd_micros': 50_000_000},
                            providers=('audiovisual_analysis',)) == ''
    assert 'run_guardrail:' in s.autorun._cover(
        loaded, {'usd_micros': 50_000_001},
        providers=('audiovisual_analysis',))


def test_run_guardrail_counts_settled_and_unknown_outcomes(application):
    s, _client, act, _worker, root = stack(application)
    run = launch(act, make_seed(act, root))
    bid = run['params']['spending_policy']['budget_id']
    ledger = BudgetService(s.db)

    first = ledger.reserve('run-cap-settled', [(bid, 20_000_000)])
    ledger.settle(first, 'reported_usage', {bid: 10_000_000}, 'fixture receipt')
    second = ledger.reserve('run-cap-unknown', [(bid, 25_000_000)])
    ledger.mark_ambiguous(second)
    assert ledger.available(bid) == 15_000_000
    with pytest.raises(ReservationBlocked, match='cap_exceeded'):
        ledger.reserve('run-cap-refused', [(bid, 15_000_001)])


def test_resume_cannot_drop_or_adopt_another_runs_guardrail(application):
    s, _client, act, _worker, root = stack(application)
    seed = make_seed(act, root)
    first = launch(act, seed)
    second = launch(act, seed)
    original = first['params']['spending_policy']['budget_id']
    foreign = second['params']['spending_policy']['budget_id']
    saved = s.autorun.get(first['id'])
    saved.status = 'paused'
    saved.pause = {'code': 'budget_exhausted', 'at': 'fixture'}
    s.autorun._put(saved)

    replaced = act('post', f"/api/autoruns/{first['id']}/resume", {
        'budget_ids': ['credits-gen', 'credits-tts', 'credits-usd']})
    assert replaced.status_code == 200, replaced.text
    assert original in replaced.json()['run']['params']['budget_ids']
    saved = s.autorun.get(first['id'])
    saved.status = 'paused'
    saved.pause = {'code': 'budget_exhausted', 'at': 'fixture-2'}
    s.autorun._put(saved)
    adopted = act('post', f"/api/autoruns/{first['id']}/resume", {
        'add_budget_ids': [foreign]})
    assert adopted.status_code == 400
    assert adopted.json()['error'] == 'budget_not_selectable'


def test_explicit_run_budget_raise_preserves_ambiguous_costs(application):
    s, _, act, _, root = stack(application)
    run = launch(act, make_seed(act, root))
    saved = s.autorun.get(run['id'])
    saved.status = 'paused'
    s.autorun._put(saved)
    bid = saved.params['spending_policy']['budget_id']
    ledger = BudgetService(s.db)
    hold = ledger.reserve('approved-raise-hold', [(bid, 34_000_000)])
    ledger.mark_ambiguous(hold)
    body = {'ceiling': 200_000_000, 'expected_ceiling': 50_000_000,
            'reviewer': 'operator', 'evidence': 'Explicit cumulative $200 approval'}
    response = act('post', f"/api/autoruns/{run['id']}/budget", body)
    assert response.status_code == 200, response.text
    assert response.json()['committed'] == 34_000_000
    assert ledger.available(bid) == 166_000_000
    assert s.autorun.detail(run['id'])['spending_policy']['cap_amount'] == 200_000_000
    assert s.db.conn.execute('SELECT status FROM reservations WHERE id=?', (hold,)).fetchone()[0] == 'ambiguous'
    with pytest.raises(ContractError, match='stale_budget_ceiling'):
        s.autorun.raise_budget(run['id'], body)
    with pytest.raises(ContractError, match='run_guardrail_mismatch'):
        ledger.create_budget(bid, 'usd_micros', 'experiment', run['id'], 250_000_000)
    with s.db.uow() as u:
        u.conn.execute('UPDATE budgets SET cap_amount=250000000 WHERE id=?', (bid,))
    with pytest.raises(ContractError, match='run_guardrail_mismatch'):
        ledger.available(bid)


@pytest.mark.parametrize('patch', [
    {'reviewer': ''}, {'evidence': ''}, {'ceiling': True},
    {'expected_ceiling': 49_000_000}, {'ceiling': 50_000_000},
])
def test_run_budget_raise_rejects_invalid_authority_without_changes(application, patch):
    s, _, act, _, root = stack(application)
    run = launch(act, make_seed(act, root))
    saved = s.autorun.get(run['id'])
    saved.status = 'paused'
    s.autorun._put(saved)
    body = {'ceiling': 200_000_000, 'expected_ceiling': 50_000_000,
            'reviewer': 'operator', 'evidence': 'Explicit cumulative approval', **patch}
    with pytest.raises(ContractError):
        s.autorun.raise_budget(run['id'], body)
    assert s.autorun.detail(run['id'])['spending_policy']['cap_amount'] == 50_000_000
    assert not s.db.conn.execute("SELECT 1 FROM events WHERE type='run_budget_raised'").fetchone()
