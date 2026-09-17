"""Durable idempotency (F27): mutation requests persist
key → request-hash → result. Identical replay returns the original;
changed payload or reused key on a different request is a conflict.
"""
import hashlib
import json
from datetime import datetime, timezone

from ..domain.errors import ContractError


def _now():
    return datetime.now(timezone.utc).isoformat()


def request_hash(method, path, body):
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method} {path} {canon}".encode()) \
        .hexdigest()


class IdempotencyStore:
    def __init__(self, db):
        self.db = db

    def run(self, key, method, path, body, fn):
        """Execute fn once per (key, request). Persisted result replays
        on identical retry; a changed payload with the same key is a
        409 — never a second effect."""
        h = request_hash(method, path, body)
        row = self.db.uow().records.get("api_request", key)
        if row is not None:
            saved = json.loads(row["body"])
            if saved["request_hash"] != h:
                raise ContractError(
                    "idempotency_conflict", "Idempotency-Key",
                    "key reused with a different request")
            return saved["status"], json.loads(saved["response"])
        status, response = fn()
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT INTO records(kind,id,revision,schema_version,"
                "status,body,created_at,updated_at,version)"
                " VALUES('api_request',?,0,'api_request.v1',?,?,?,?,1)",
                (key, "done",
                 json.dumps({"request_hash": h, "method": method,
                             "path": path, "status": status,
                             "response": json.dumps(response)}),
                 _now(), _now()))
        return status, response
