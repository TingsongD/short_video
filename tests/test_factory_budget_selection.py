from test_factory_api import env, mut
import pytest


def test_internal_ceiling_is_visible_but_cannot_fund_a_new_run(env):
    client, csrf, _, s, _ = env
    from modules.factory.budget import BudgetService
    ledger = BudgetService(s.db)
    ledger.create_budget('authority:private:usd', 'usd_micros', 'aggregate', cap=100)
    ledger.create_budget('funded', 'usd_micros', 'aggregate', cap=100)
    rows = {b['id']: b for b in client.get('/api/collections/budgets').json()['items']}
    assert rows['authority:private:usd']['selection_eligible'] is False
    assert rows['authority:private:usd']['classification'] == 'internal_authority'
    assert rows['funded']['selection_eligible'] is True
    response = mut(client, csrf, 'post', '/api/autoruns', json={
        'seed_id': 'unused', 'voice_id': 'fixture', 'budget_ids': ['authority:private:usd']})
    assert response.status_code == 400
    assert response.json()['error'] == 'budget_not_selectable'
    assert not s.autorun.list()


@pytest.mark.parametrize('path,field', [
    ('/api/autoruns','budget_ids'),
    ('/api/autoruns/unused/resume','add_budget_ids'),
    ('/api/experiments/unused/authorize','budget_ids'),
])
@pytest.mark.parametrize('internal', [True, False])
def test_user_funding_boundaries_reject_internal_and_retired_budgets(env, path, field, internal):
    client, csrf, db, s, _ = env
    from modules.factory.budget import BudgetService
    bid = 'authority:private:usd' if internal else 'retired-budget'
    BudgetService(db).create_budget(bid, 'usd_micros', 'aggregate', cap=100)
    if not internal:
        with db.uow() as u:
            u.conn.execute('INSERT INTO meta(key,value) VALUES(?,?)', ('retired:budget:'+bid,'true'))
    response = mut(client, csrf, 'post', path, rev=1, json={field:[bid]})
    assert response.status_code == 400, response.text
    assert response.json()['error'] == 'budget_not_selectable'
    assert db.conn.execute('SELECT COUNT(*) FROM reservations').fetchone()[0] == 0
