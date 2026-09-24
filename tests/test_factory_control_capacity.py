"""Control commands must remain runnable when remote outcomes fill dispatch."""
from modules.factory.domain import Job
from modules.factory.scheduler import Scheduler
from modules.factory.services.commands import CommandQueue
from modules.factory.store import Database


def test_autostep_can_reconcile_full_dispatch_without_freeing_remote_holds(tmp_path):
    db = Database(tmp_path / 'factory.db')
    scheduler = Scheduler(db, worker_id='test')
    commands = CommandQueue(db, scheduler)
    for index in range(4):
        scheduler.submit_plan([Job(schema_version='job.v1', id=f'paid-{index}',
            logical_key=f'paid-{index}', created_at='2026-01-01T00:00:00Z', phase='analyze')])
        assert scheduler.claim()['id'] == f'paid-{index}'
    before = [tuple(row) for row in db.conn.execute('SELECT * FROM capacity_holds')]
    commands.enqueue('auto_step', {'run_id': 'run'}, identity='existing-autostep', phase='plan')
    commands.enqueue('other_plan', {}, identity='ordinary-plan', phase='plan')
    scheduler.pause()
    assert scheduler.claim() is None
    scheduler.resume()
    claim = scheduler.claim()
    assert claim is not None, 'Recovery controller starved behind the work it must reconcile'
    assert claim['id'] == 'existing-autostep'
    assert [tuple(row) for row in db.conn.execute("SELECT * FROM capacity_holds WHERE capacity='dispatch'")] == before
    assert scheduler.claim() is None
    scheduler.complete(claim['id'], claim['fencing_token'])
    assert scheduler.claim() is None
    db.close()


def test_recovery_readiness_checks_controller_capacity_not_paid_dispatch():
    from types import SimpleNamespace
    import pytest
    from modules.factory.autorun.readiness import runtime_ready
    from modules.factory.domain.errors import ContractError
    capacities = {'dispatch': {'used': 4, 'limit': 4}, 'observe': {'used': 0, 'limit': 2}}
    worker = {'available': True, 'paused': False, 'draining': False}
    services = SimpleNamespace(config={'mode': 'live'}, health=lambda: {'worker': worker},
        scheduler=SimpleNamespace(status_snapshot=lambda: {'capacities': capacities}))
    runtime_ready(services, capacity_pool='observe')
    with pytest.raises(ContractError, match='queue_capacity_full'):
        runtime_ready(services)
    worker['paused'] = True
    with pytest.raises(ContractError, match='queue_paused'):
        runtime_ready(services, capacity_pool='observe')
    worker['paused'] = False
    capacities['observe']['used'] = 2
    with pytest.raises(ContractError, match='queue_capacity_full'):
        runtime_ready(services, capacity_pool='observe')
