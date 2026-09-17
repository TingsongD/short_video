"""F03 — SQLite store: transactions, CAS, outbox atomicity, migrations,
backup/restore, forward-compat refusal. All offline."""
import os
import sqlite3
import threading

import pytest

from modules.factory.domain import ContractError, ExperimentRevision, Job
from modules.factory.domain.records import content_hash
from modules.factory.store import (Database, NewerDatabaseError,
                                   StaleRevisionError, backup, connection)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "factory.db")
    yield d
    d.close()


def _experiment(eid="exp:1", rev=1, status="draft"):
    return ExperimentRevision(
        schema_version="experiment_revision.v1", id=f"er:{eid}:{rev}",
        created_at="2026-09-16T00:00:00Z", experiment_id=eid,
        revision=rev, status=status)


class TestSchemaAndMigration:
    def test_wal_and_fk_enabled(self, db):
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_migration_applies_in_order(self, tmp_path):
        conn = connection.open(str(tmp_path / "m.db"))
        assert connection.current_version(conn) == \
            connection._schema.CURRENT_VERSION
        # every migration's tables exist
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"records", "jobs", "attempts", "events", "outbox",
                "intents", "artifacts"} <= tables
        conn.close()

    def test_newer_database_refused(self, db):
        db.conn.execute(
            "UPDATE meta SET value='99' WHERE key='schema_version'")
        db.conn.commit()
        db.close()
        with pytest.raises(NewerDatabaseError):
            Database(db.path)

    def test_readonly_open(self, db):
        ro = db.readonly()
        ro.execute("SELECT * FROM jobs").fetchall()
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO jobs(id,logical_key,phase,status,"
                       "created_at,updated_at) VALUES('x','x','x','x','x','x')")
        ro.close()


class TestUnitOfWork:
    def test_commit_persists_and_rollback_discards(self, db):
        with db.uow() as u:
            u.records.put(_experiment())
            u.events.append("experiment:exp:1", "created", {"id": "exp:1"})
        assert db.uow().records.get("experimentrevision", "er:exp:1:1")
        with pytest.raises(RuntimeError):
            with db.uow() as u:
                u.records.put(_experiment(rev=2))
                u.events.append("experiment:exp:1", "edited", {})
                raise RuntimeError("boom")
        # nothing from the failed transaction survived
        assert db.uow().records.get("experimentrevision", "er:exp:1:2") is None
        evs = db.uow().events.since("experiment:exp:1")
        assert [e["type"] for e in evs] == ["created"]

    def test_transition_and_event_commit_together(self, db):
        with db.uow() as u:
            j = Job(schema_version="job.v1", id="j:1",
                    created_at="2026-09-16T00:00:00Z",
                    logical_key="lk1", phase="generate", status="ready")
            u.jobs.put(j)
            u.events.append("job:j:1", "became_ready", {"job": "j:1"})
        row = db.uow().jobs.get("j:1")
        assert row["status"] == "ready"
        assert len(db.uow().events.since("job:j:1")) == 1

    def test_cas_conflict(self, db):
        with db.uow() as u:
            u.records.put(_experiment())
        row = db.uow().records.get("experimentrevision", "er:exp:1:1")
        e = _experiment()
        e.status = "accepted"
        e.content_hash = content_hash(e.to_dict())
        with db.uow() as u:
            u.records.put(e, expected_version=row["version"])
        with pytest.raises(StaleRevisionError):
            with db.uow() as u:
                u.records.put(e, expected_version=row["version"])

    def test_two_writers_one_wins(self, db):
        with db.uow() as u:
            u.records.put(_experiment())
        row = db.uow().records.get("experimentrevision", "er:exp:1:1")
        results = []
        def writer(tag):
            try:
                e = _experiment()
                e.status = f"edited_by_{tag}"
                with db.uow() as u:
                    u.records.put(e, expected_version=row["version"])
                results.append((tag, "ok"))
            except StaleRevisionError:
                results.append((tag, "stale"))
            except sqlite3.OperationalError:
                results.append((tag, "busy"))
        writer("a")
        writer("b")
        assert sorted(results) == [("a", "ok"), ("b", "stale")]

    def test_outbox_atomicity(self, db):
        with pytest.raises(RuntimeError):
            with db.uow() as u:
                u.outbox.enqueue("intent:1", "provider_submit",
                                 {"request_hash": "r1"})
                raise RuntimeError("crash before dispatch")
        assert db.uow().outbox.pending() == []
        with db.uow() as u:
            u.outbox.enqueue("intent:1", "provider_submit",
                             {"request_hash": "r1"})
            u.intents.create("intent:1", "r1", "provider_submit", {})
        assert len(db.uow().outbox.pending()) == 1
        # same request_hash+kind cannot create a second intent
        with pytest.raises(ContractError):
            with db.uow() as u:
                u.intents.create("intent:2", "r1", "provider_submit", {})

    def test_job_logical_key_unique(self, db):
        j = Job(schema_version="job.v1", id="j:1",
                created_at="2026-09-16T00:00:00Z",
                logical_key="dup", phase="p", status="ready")
        with db.uow() as u:
            u.jobs.put(j)
        j2 = Job(schema_version="job.v1", id="j:2",
                 created_at="2026-09-16T00:00:00Z",
                 logical_key="dup", phase="p", status="ready")
        with pytest.raises(sqlite3.IntegrityError):
            with db.uow() as u:
                u.jobs.put(j2)


class TestConcurrency:
    def test_concurrent_writers_serialize(self, db):
        errs = []
        def writer(i):
            own = Database(db.path)
            try:
                for n in range(5):
                    with own.uow() as u:
                        u.events.append("stress", f"e{i}-{n}", {"i": i})
            except Exception as e:                     # noqa: BLE001
                errs.append(e)
            finally:
                own.close()
        threads = [threading.Thread(target=writer, args=(i,))
                   for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errs
        assert len(db.uow().events.since("stress")) == 20


class TestBackupRestore:
    def test_backup_and_verify(self, db, tmp_path):
        with db.uow() as u:
            u.records.put(_experiment())
            u.events.append("experiment:exp:1", "created", {})
        dest = tmp_path / "backup.db"
        info = backup.backup(db.path, dest)
        assert info == {"integrity": "ok",
                        "schema_version": connection._schema.CURRENT_VERSION}
        conn = sqlite3.connect(str(dest))
        n = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        assert n == 1
        conn.close()

    def test_restore_to_separate_path(self, db, tmp_path):
        with db.uow() as u:
            u.records.put(_experiment())
        dest = tmp_path / "copy.db"
        info = backup.restore(db.path, dest)
        assert info["integrity"] == "ok"
        with pytest.raises(ContractError):
            backup.restore(db.path, dest)   # refuse overwrite

    def test_backup_captures_wal_contents(self, db, tmp_path):
        with db.uow() as u:
            u.events.append("s", "e", {"k": "wal-only"})
        dest = tmp_path / "wal.db"
        backup.backup(db.path, dest)
        conn = sqlite3.connect(str(dest))
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        conn.close()


class TestFailureBoundaries:
    def test_partial_write_leaves_no_orphans(self, db):
        with pytest.raises(RuntimeError):
            with db.uow() as u:
                j = Job(schema_version="job.v1", id="j:x",
                        created_at="2026-09-16T00:00:00Z",
                        logical_key="lk-x", phase="p", status="ready")
                u.jobs.put(j)
                from modules.factory.domain import Attempt
                u.attempts.put(Attempt(
                    schema_version="attempt.v1", id="at:1",
                    created_at="2026-09-16T00:00:00Z", job_id="j:x",
                    attempt_seq=1))
                raise RuntimeError("crash mid-transaction")
        assert db.uow().jobs.get("j:x") is None
        # no orphan attempt either
        assert db.conn.execute(
            "SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
