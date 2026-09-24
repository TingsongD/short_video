"""Concurrent remote footage through the real worker; all providers are local."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from modules.factory.bootstrap import bootstrap
from modules.factory.budget import BudgetService
from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import ExperimentRevision
from modules.factory.providers.catalog import CapabilityCatalog, CapabilitySnapshot, snapshot_id
from modules.factory.services.worker import ApplicationWorker
from modules.factory.testing.authority import approve_production
from modules.factory.testing.durable import DiskGeneration
from modules.factory.testing.fakes import ProviderError


class SlowGeneration(DiskGeneration):
    """Polls consume simulated time; only explicitly completed requests finish."""
    account = 'offline-fixture-account'

    def __init__(self, root):
        super().__init__(root, 'google_vertex')
        self.done = set()
        self.now = datetime.now(timezone.utc)

    def poll(self, oid):
        self.now += timedelta(seconds=3)
        row = super().poll(oid)
        row['status'] = 'succeeded' if oid in self.done else 'running'
        return row

    def operations(self):
        return [json.loads(p.read_text()) for p in self.remote.glob('*.json')]


@pytest.fixture
def parallel(tmp_path, request):
    provider = SlowGeneration(tmp_path)
    s = bootstrap(tmp_path, providers={'google_vertex': provider},
                  settings={'mode': 'offline', 'raise_worker_errors': True})
    s.scheduler.clock = lambda: provider.now
    CapabilityCatalog(s.db).put(CapabilitySnapshot(
        schema_version='capability_snapshot.v1',
        id=snapshot_id('google_vertex', 'fixture-fast', '', 'text'),
        created_at=provider.now.isoformat(), provider='google_vertex',
        model='fixture-fast', input_mode='text', support='observed',
        capabilities=provider.capabilities('fixture-fast'),
        valid_until=(provider.now + timedelta(hours=1)).isoformat()))
    with s.db.uow() as u:
        u.records.put(ExperimentRevision(schema_version='experiment.v1',
            id='exp:parallel', experiment_id='parallel', revision=1,
            packaging={'workflow': {'version': 2}}))
    takes = [{'variant': 'A', 'slot': f's{i}', 'duration_s': getattr(request, 'param', 1),
              'request': {'prompt': f'Independent scene {i}',
                          'settings': {'resolution': '180x320', 'aspect': '9:16'}}}
             for i in range(6)]
    s.production.adapter = provider
    s.production.plan('parallel', 'parallel', 1, takes, 'google_vertex',
                      'fixture-fast', [1], now=provider.now.isoformat())
    approve_production(s.production, 'parallel')
    s.production.submit('parallel')
    yield s, ApplicationWorker(s), provider
    s.db.close()


def tick_until(worker, predicate, limit=40):
    for _ in range(limit):
        if predicate():
            return
        worker.tick()
    assert predicate(), 'Worker did not make progress within the bounded ticks'


@pytest.mark.parametrize('parallel', [5], indirect=True)
def test_split_scenes_poll_existing_operations_when_all_submit_slots_are_full(parallel):
    s, worker, provider = parallel
    tick_until(worker, lambda: len(provider.operations()) == 4)
    original = {op['operation_id'] for op in provider.operations()}
    for _ in range(8):
        worker.tick()
    assert len(provider.operations()) == 4
    # Each scene requires five allocations. Jobs deferred midway through
    # submission must observe their accepted allocations before requesting
    # another slot, even when every remote slot is occupied.
    # Match the recovered production state: transient worker leases are gone,
    # while durable per-attempt remote holds still account for all four slots.
    with s.db.uow() as u:
        u.conn.execute("DELETE FROM capacity_holds WHERE capacity='vertex_submit'")
    assert s.db.conn.execute('SELECT count(*) FROM remote_holds').fetchone()[0] == 4
    provider.done.update(original)
    provider.now += timedelta(seconds=10)
    tick_until(worker, lambda: len(provider.operations()) > 4)
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['used'] <= 4
    assert len({op['operation_id'] for op in provider.operations()}) == len(provider.operations())


def test_slow_polls_allow_four_in_flight_and_refill_after_out_of_order_completion(parallel):
    s, worker, provider = parallel
    tick_until(worker, lambda: len(provider.operations()) == 4)
    for _ in range(8):
        worker.tick()
    original = {op['operation_id'] for op in provider.operations()}
    assert len(original) == 4
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['used'] == 4
    assert BudgetService(s.db).available('fixture:parallel:usd_micros') == 2
    assert not s.db.conn.execute("SELECT 1 FROM attempts WHERE status='downloaded'").fetchone()

    # The oldest request stays slow. A later completion must be collected
    # while paused, without admitting another paid request.
    s.scheduler.pause()
    rows = s.db.conn.execute('SELECT id,remote_id FROM attempts ORDER BY created_at').fetchall()
    completed = rows[-1]
    provider.done.add(completed['remote_id'])
    tick_until(worker, lambda: s.db.conn.execute(
        'SELECT status FROM attempts WHERE id=?', (completed['id'],)).fetchone()[0] == 'downloaded')
    assert {op['operation_id'] for op in provider.operations()} == original
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['used'] == 3

    s.scheduler.resume()
    tick_until(worker, lambda: len(provider.operations()) == 5)
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['used'] == 4
    assert s.db.conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 5
    assert s.db.conn.execute("SELECT status FROM attempts WHERE id=?", (rows[0]['id'],)).fetchone()[0] == 'running'


def test_parallel_requests_cannot_exceed_the_funded_budget(parallel):
    s, worker, provider = parallel
    s.db.conn.execute("UPDATE budgets SET cap_amount=2 WHERE id='fixture:parallel:usd_micros'")
    for _ in range(30):
        worker.tick()
    assert len(provider.operations()) == 2
    assert BudgetService(s.db).available('fixture:parallel:usd_micros') == 0
    assert s.db.conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 2


def test_lowering_concurrency_keeps_inflight_identity_and_holds(parallel):
    s, worker, provider = parallel
    tick_until(worker, lambda: len(provider.operations()) == 4)
    before = [tuple(r) for r in s.db.conn.execute('SELECT * FROM remote_holds ORDER BY attempt_id')]
    s.scheduler.configure_vertex_concurrency(1)
    restarted = ApplicationWorker(s)
    for _ in range(8):
        restarted.tick()
    assert len(provider.operations()) == 4
    assert before == [tuple(r) for r in s.db.conn.execute('SELECT * FROM remote_holds ORDER BY attempt_id')]
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit'] == {'limit': 1, 'used': 4}


def test_lost_submission_response_keeps_one_of_four_slots_after_restart(parallel, monkeypatch):
    s, worker, provider = parallel
    original_submit = provider.submit
    lost = []

    def submit(request, price=None):
        result = original_submit(request, price)
        if not lost:
            lost.append(result['operation_id'])
            raise ProviderError('response_lost', transient=True)
        return result

    monkeypatch.setattr(provider, 'submit', submit)
    tick_until(worker, lambda: len(provider.operations()) == 4)
    restarted = ApplicationWorker(s)
    for _ in range(12):
        restarted.tick()
    assert len(provider.operations()) == 4
    assert s.db.conn.execute("SELECT COUNT(*) FROM attempts WHERE status='unknown'").fetchone()[0] == 1
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['used'] == 4
    assert BudgetService(s.db).available('fixture:parallel:usd_micros') == 2


def test_bootstrap_applies_parallel_default_to_existing_database(tmp_path, monkeypatch):
    monkeypatch.delenv('FACTORY_VERTEX_CONCURRENCY', raising=False)
    s = bootstrap(tmp_path, providers={})
    s.scheduler.configure_vertex_concurrency(1)
    s.db.close()
    s = bootstrap(tmp_path, providers={})
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['limit'] == 4
    s.db.close()
    (tmp_path / '.env').write_text('FACTORY_VERTEX_CONCURRENCY=2\n')
    s = bootstrap(tmp_path, providers={})
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['limit'] == 2
    s.db.close()
    monkeypatch.setenv('FACTORY_VERTEX_CONCURRENCY', '0')
    s = bootstrap(tmp_path, providers={})
    assert s.scheduler.status_snapshot()['capacities']['vertex_submit']['limit'] == 0
    s.db.close()


@pytest.mark.parametrize('value', [-1, 17, True, 2.5, '2.5', 'unlimited', ''])
def test_invalid_concurrency_fails_before_startup(tmp_path, value):
    with pytest.raises(ContractError, match='invalid_vertex_concurrency'):
        bootstrap(tmp_path, providers={}, settings={'vertex_concurrency': value})
    assert not (tmp_path / 'data/factory/factory.db').exists()
