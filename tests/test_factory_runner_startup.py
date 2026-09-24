"""A supervisor that never claims its intent must not consume a render timeout."""
from types import SimpleNamespace

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.resources.runner import OwnedRunner
from modules.factory.store import Database


def test_exited_supervisor_reports_startup_failure_promptly(tmp_path, monkeypatch):
    import modules.factory.resources.runner as module
    clock = iter([0, 0, 7206])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(poll=lambda: 1))
    db = Database(tmp_path/'db')
    try:
        with pytest.raises(ContractError, match='local_supervisor_start_failed'):
            OwnedRunner(db, tmp_path/'processes', 'startup-test')(['unused'], timeout=7200)
    finally:
        db.close()


def test_supervisor_receipt_wins_over_exit_status(tmp_path, monkeypatch):
    import modules.factory.resources.runner as module
    from modules.factory.providers.state import DurableState
    def launch(*args, **kwargs):
        state = DurableState(args[0][-1])
        state.update(status='done', returncode=0, stdout='finished', stderr='')
        state.flush()
        return SimpleNamespace(poll=lambda: 1, wait=lambda timeout: 1)
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    db = Database(tmp_path/'db')
    try:
        result = OwnedRunner(db, tmp_path/'processes', 'receipt-test')(['unused'])
        assert result.returncode == 0 and result.stdout == 'finished'
    finally:
        db.close()
