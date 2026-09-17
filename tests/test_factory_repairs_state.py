"""Restore and migration checks against public operations boundaries."""
from pathlib import Path
import json
import sqlite3
import pytest

from modules.factory.cli import main
from modules.factory.store import Database
from modules.factory.operations import create_backup, restore_into, activation_gate
from modules.factory.budget.service import BudgetService


def test_cli_reopens_restored_budget_and_keeps_dispatch_blocked(tmp_path, capsys):
    db = Database(tmp_path / "source.db")
    BudgetService(db).create_budget("test-cap", "jimeng_credits", "aggregate", cap=100)
    create_backup(db, tmp_path, tmp_path / "backup")
    restored = tmp_path / "restored"
    restore_into(tmp_path / "backup", restored)
    assert main(["--root", str(restored), "gate"]) == 1
    assert not json.loads(capsys.readouterr().out)["allowed"]
    reopened = Database(restored / "data" / "factory" / "factory.db")
    assert BudgetService(reopened).available("test-cap") == 100
    assert not activation_gate(reopened)["dispatch_enabled"]


def test_interrupted_migration_preserves_last_version_and_retries(tmp_path, monkeypatch):
    from modules.factory.store import connection, schema
    conn = sqlite3.connect(tmp_path / "old.db", isolation_level=None)
    for version, ddl in schema.MIGRATIONS[:7]:
        conn.executescript(ddl)
        conn.execute("INSERT OR REPLACE INTO meta VALUES('schema_version',?)", (str(version),))
    with monkeypatch.context() as fault:
        fault.setattr(schema, "MIGRATIONS", [(8, "CREATE TABLE probe(value); INVALID SQL;")])
        with pytest.raises(sqlite3.OperationalError):
            connection.migrate(conn)
    assert connection.current_version(conn) == 7
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='probe'").fetchone()
    assert connection.migrate(conn) == schema.CURRENT_VERSION


def test_backup_rejects_missing_explicit_financial_file(tmp_path):
    from modules.factory.domain.errors import ContractError
    with pytest.raises(ContractError, match="backup_missing_ledger"):
        create_backup(Database(tmp_path / "db"), tmp_path, tmp_path / "backup",
                      ledger_paths=[tmp_path / "lost-ledger.json"])
