"""Unit of work: repositories share one transaction. State transitions and
their events commit together; external intents go to the outbox in the
same transaction — dispatch happens after commit, never inside."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from ..domain.errors import ContractError
from ..domain.records import canonical
from . import connection


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class StaleRevisionError(ContractError):
    def __init__(self, what):
        super().__init__("stale_revision", what,
                         "row changed since read; reload and retry")


class Records:
    def __init__(self, conn):
        self.conn = conn

    def put(self, record, expected_version=None):
        """Insert or CAS-update a domain record. expected_version=None
        inserts; an int performs optimistic concurrency."""
        body = record.to_dict()
        now = utcnow()
        if expected_version is None:
            try:
                self.conn.execute(
                    "INSERT INTO records(kind,id,revision,schema_version,"
                    "status,parent_hash,content_hash,body,created_at,"
                    "updated_at,version) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                    (type(record).__name__.lower(), record.id,
                     getattr(record, "revision", 0) or 0,
                     record.schema_version,
                     getattr(record, "status", ""),
                     getattr(record, "parent_hash", "") or None,
                     getattr(record, "content_hash", "") or None,
                     canonical(body), record.created_at or now, now))
            except sqlite3.IntegrityError as e:
                raise ContractError("record_conflict", record.id, str(e))
        else:
            cur = self.conn.execute(
                "UPDATE records SET status=?, content_hash=?, body=?, "
                "updated_at=?, version=version+1 WHERE kind=? AND id=? "
                "AND revision=? AND version=?",
                (getattr(record, "status", ""),
                 getattr(record, "content_hash", "") or None,
                 canonical(body), now,
                 type(record).__name__.lower(), record.id,
                 getattr(record, "revision", 0) or 0, expected_version))
            if cur.rowcount == 0:
                raise StaleRevisionError(record.id)

    def get(self, kind, rid, revision=None):
        if revision is None:
            row = self.conn.execute(
                "SELECT * FROM records WHERE kind=? AND id=? "
                "ORDER BY revision DESC LIMIT 1", (kind, rid)).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM records WHERE kind=? AND id=? AND revision=?",
                (kind, rid, revision)).fetchone()
        return dict(row) if row else None

    def revisions(self, kind, rid):
        rows = self.conn.execute(
            "SELECT * FROM records WHERE kind=? AND id=? "
            "ORDER BY revision", (kind, rid)).fetchall()
        return [dict(r) for r in rows]


class Jobs:
    def __init__(self, conn):
        self.conn = conn

    def put(self, job, expected_version=None):
        now = utcnow()
        if expected_version is None:
            self.conn.execute(
                "INSERT INTO jobs(id,logical_key,phase,experiment_id,"
                "revision,variant_key,status,depends_on,retry_class,"
                "created_at,updated_at,version) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                (job.id, job.logical_key, job.phase, job.experiment_id,
                 job.revision, job.variant_key, job.status,
                 json.dumps(job.depends_on), job.retry_class,
                 job.created_at or now, now))
        else:
            cur = self.conn.execute(
                "UPDATE jobs SET status=?, lease_owner=?, lease_expires=?,"
                "fencing_token=?, blocked_reason=?, updated_at=?,"
                "version=version+1 WHERE id=? AND version=?",
                (job.status, job.lease_owner or None, job.lease_expires or None,
                 job.fencing_token, job.blocked_reason or None, now,
                 job.id, expected_version))
            if cur.rowcount == 0:
                raise StaleRevisionError(job.id)

    def get(self, job_id):
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?",
                                (job_id,)).fetchone()
        return dict(row) if row else None

    def by_logical_key(self, key):
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE logical_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def ready(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM jobs WHERE status IN ('ready','waiting_dependencies')"
            " ORDER BY created_at").fetchall()]


class Attempts:
    def __init__(self, conn):
        self.conn = conn

    def put(self, attempt):
        now = utcnow()
        try:
            self.conn.execute(
                "INSERT INTO attempts(id,job_id,attempt_seq,request_hash,"
                "remote_id,status,body,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (attempt.id, attempt.job_id, attempt.attempt_seq,
                 attempt.request_hash or None, attempt.remote_id or None,
                 attempt.status, canonical(attempt.to_dict()), now, now))
        except sqlite3.IntegrityError as e:
            raise ContractError("attempt_conflict", attempt.id, str(e))

    def by_remote(self, remote_id):
        rows = self.conn.execute(
            "SELECT * FROM attempts WHERE remote_id=? ORDER BY created_at",
            (remote_id,)).fetchall()
        return [dict(r) for r in rows]

    def unfinished(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM attempts WHERE status IN "
            "('prepared','dispatching','accepted','running','unknown',"
            "'cancel_requested')").fetchall()]


class Events:
    def __init__(self, conn):
        self.conn = conn

    def append(self, stream, etype, body):
        cur = self.conn.execute(
            "INSERT INTO events(stream,type,body,created_at) "
            "VALUES(?,?,?,?)",
            (stream, etype, canonical(body), utcnow()))
        return cur.lastrowid

    def since(self, stream, seq=0):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM events WHERE stream=? AND seq>? ORDER BY seq",
            (stream, seq)).fetchall()]


class Outbox:
    def __init__(self, conn):
        self.conn = conn

    def enqueue(self, intent_key, kind, body):
        try:
            self.conn.execute(
                "INSERT INTO outbox(intent_key,kind,body,status,created_at)"
                " VALUES(?,?,?,'pending',?)",
                (intent_key, kind, canonical(body), utcnow()))
        except sqlite3.IntegrityError as e:
            raise ContractError("duplicate_intent", intent_key, str(e))

    def pending(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM outbox WHERE status='pending' ORDER BY seq"
        ).fetchall()]

    def mark(self, intent_key, status):
        self.conn.execute(
            "UPDATE outbox SET status=?, dispatched_at=? WHERE intent_key=?",
            (status, utcnow(), intent_key))


class Intents:
    def __init__(self, conn):
        self.conn = conn

    def create(self, intent_key, request_hash, kind, body):
        now = utcnow()
        try:
            self.conn.execute(
                "INSERT INTO intents(intent_key,request_hash,kind,body,"
                "status,created_at) VALUES(?,?,?,?,'prepared',?)",
                (intent_key, request_hash, kind, canonical(body), now))
        except sqlite3.IntegrityError as e:
            raise ContractError("duplicate_intent", intent_key, str(e))

    def by_request_hash(self, request_hash, kind=None):
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM intents WHERE request_hash=? AND kind=?",
                (request_hash, kind)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM intents WHERE request_hash=?",
                (request_hash,)).fetchall()
        return [dict(r) for r in rows]

    def attach_remote(self, intent_key, remote_id, status="dispatched"):
        cur = self.conn.execute(
            "UPDATE intents SET remote_id=?, status=? WHERE intent_key=?",
            (remote_id, status, intent_key))
        if cur.rowcount == 0:
            raise ContractError("missing_intent", intent_key)


class Artifacts:
    def __init__(self, conn):
        self.conn = conn

    def register(self, artifact, status="registered"):
        now = utcnow()
        self.conn.execute(
            "INSERT INTO artifacts(id,sha256,kind,byte_count,probe,"
            "provenance,local_path,status,body,created_at,updated_at,"
            "version) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
            (artifact.id, artifact.sha256 or None, artifact.kind,
             artifact.byte_count, canonical(artifact.probe),
             artifact.provenance or None, artifact.local_path or None,
             status, canonical(artifact.to_dict()), now, now))

    def get(self, artifact_id):
        row = self.conn.execute("SELECT * FROM artifacts WHERE id=?",
                                (artifact_id,)).fetchone()
        return dict(row) if row else None

    def by_sha(self, sha256):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM artifacts WHERE sha256=?", (sha256,)).fetchall()]

    def missing(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM artifacts WHERE status='missing'").fetchall()]


class UnitOfWork:
    """One transaction across all repositories. Commit or roll back
    atomically; external calls never happen inside the `with` block."""

    def __init__(self, conn):
        self.conn = conn
        self.records = Records(conn)
        self.jobs = Jobs(conn)
        self.attempts = Attempts(conn)
        self.events = Events(conn)
        self.outbox = Outbox(conn)
        self.intents = Intents(conn)
        self.artifacts = Artifacts(conn)
        self._active = False

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self._active = False
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.conn = connection.open(self.path)

    def uow(self):
        return UnitOfWork(self.conn)

    def readonly(self):
        return connection.open(self.path, readonly=True)

    def close(self):
        self.conn.close()

    def backup_to(self, dest_path):
        """SQLite online backup — safe on a live WAL database."""
        dest = sqlite3.connect(str(dest_path))
        self.conn.backup(dest)
        dest.close()
        return dest_path
