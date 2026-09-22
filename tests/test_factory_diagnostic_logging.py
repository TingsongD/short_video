"""Manual service commands must leave bounded, credential-safe diagnostics."""
import json
import stat

import pytest

from modules.factory.bootstrap import bootstrap
from modules.factory.cli import main


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_manual_worker_logs_failed_job_and_restart_without_duplicate_handlers(tmp_path):
    services = bootstrap(tmp_path)
    job = services.commands.enqueue("unsupported", {"description": "private-payload"})["job_id"]
    services.db.close()
    assert main(["--root", str(tmp_path), "worker", "--once"]) == 0
    assert main(["--root", str(tmp_path), "worker", "--once"]) == 0
    path = tmp_path / ".run" / "factory-worker.jsonl"
    events = records(path)
    assert sum(r["event"] == "service_started" for r in events) == 2
    failed = next(r for r in events if r["event"] == "job_blocked")
    assert failed["job_id"] == job and failed["code"] == "handler_unavailable"
    assert all(r["pid"] and r["at"] and r["service"] == "worker" for r in events)
    assert "private-payload" not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_manual_api_logs_typed_preview_failure_without_payloads(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import sqlite3
    import uvicorn
    from modules.factory.store.uow import Database
    def unavailable(_db):
        raise sqlite3.InterfaceError("private-token and signed-url")
    monkeypatch.setattr(Database, "readonly", unavailable)
    def serve(app, **_):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/assets/fixture/media?token=private-token")
            assert response.status_code == 500
            assert "private-token" not in response.text
    monkeypatch.setattr(uvicorn, "run", serve)
    assert main(["--root", str(tmp_path), "serve"]) == 0
    path = tmp_path / ".run" / "factory-api.jsonl"
    events = records(path)
    failed = next(r for r in events if r["event"] == "request_failed")
    assert failed["error_type"] == "InterfaceError"
    assert failed["route"] == "/api/assets/{asset_id}/media"
    assert "private-token" not in path.read_text()


def test_startup_failure_is_logged_without_exception_text(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("modules.factory.bootstrap")
    def fail(_):
        raise RuntimeError("private-token")
    monkeypatch.setattr(module, "bootstrap", fail)
    with pytest.raises(RuntimeError):
        main(["--root", str(tmp_path), "worker", "--once"])
    path = tmp_path / ".run" / "factory-worker.jsonl"
    assert any(r["event"] == "service_failed" and r["error_type"] == "RuntimeError" for r in records(path))
    assert "private-token" not in path.read_text()


def test_cli_diagnostics_rotate_and_preserve_private_permissions(tmp_path, monkeypatch):
    import uvicorn
    from modules.factory.diagnostics import event
    def serve(*args, **kwargs):
        for _ in range(16000):
            event("job_result", job_id="j" * 240, status="pending")
    monkeypatch.setattr(uvicorn, "run", serve)
    assert main(["--root", str(tmp_path), "serve"]) == 0
    paths = list((tmp_path / ".run").glob("factory-api.jsonl*"))
    assert 2 <= len(paths) <= 4
    assert all(p.stat().st_size <= 4 * 1024 * 1024 for p in paths)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in paths)


def test_access_logs_strip_queries_and_exception_credentials(tmp_path, monkeypatch):
    import logging
    import uvicorn
    def serve(*args, **kwargs):
        logging.getLogger('uvicorn.access').info('%s - "%s %s HTTP/%s" %d',
            '127.0.0.1', 'GET', '/?code=private-code&state=private-state', '1.1', 404)
        try:
            raise ValueError('https://example.test/?access_token=private-token')
        except ValueError:
            logging.getLogger('uvicorn.error').exception('request rejected')
    monkeypatch.setattr(uvicorn, 'run', serve)
    main(['--root', str(tmp_path), 'serve'])
    path = tmp_path / '.run' / 'api.log'
    text = path.read_text()
    assert 'private-' not in text
    assert '404' in text and 'ValueError' in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_second_console_writer_is_refused(tmp_path):
    from modules.factory.diagnostics import console_logging
    with console_logging(tmp_path, 'api'):
        with pytest.raises(RuntimeError, match='Another service owns'):
            with console_logging(tmp_path, 'api'): pass


def test_second_service_never_writes_structured_log(tmp_path):
    from modules.factory.diagnostics import service_logging
    with service_logging(tmp_path, 'api'):
        with pytest.raises(RuntimeError, match='Another service owns'):
            with service_logging(tmp_path, 'api'): pass
    events = records(tmp_path / '.run' / 'factory-api.jsonl')
    assert [r['event'] for r in events] == ['service_started', 'service_stopped']
