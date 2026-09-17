"""Durable action ownership: uncertain actions are reconciled, never replayed."""
import hashlib
import json
from datetime import datetime, timezone
from ..domain.errors import ContractError
from ..events.redact import redact


def _now():
    return datetime.now(timezone.utc).isoformat()


def request_hash(method, path, body):
    canon = json.dumps(body, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(f'{method} {path} {canon}'.encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, db):
        self.db = db

    def run_local(self, key, method, path, body, fn):
        fingerprint = request_hash(method, path, body)
        with self.db.uow() as u:
            row = u.records.get('api_request', key)
            if row:
                saved = json.loads(row['body'])
                if saved['request_hash'] != fingerprint:
                    raise ContractError('idempotency_conflict', 'Idempotency-Key', 'key reused with a different request')
                if row['status'] == 'done':
                    return saved['status'], json.loads(saved['response'])
                if row['status'] == 'rejected':
                    raise ContractError(**saved['error'])
                raise ContractError('idempotency_unresolved', 'Idempotency-Key', 'inspect the durable action before retrying')
            saved = {'request_hash': fingerprint, 'method': method, 'path': path}
            u.conn.execute("INSERT INTO records(kind,id,revision,schema_version,status,body,created_at,updated_at) VALUES('api_request',?,0,'api_request.v2','in_progress',?,?,?)",
                           (key, json.dumps(saved), _now(), _now()))
            # API commands only mutate local state or enqueue work. The action,
            # domain records, job and response share this transaction. A process
            # loss rolls all of them back, so retry cannot strand an action.
            status, response = fn()
            saved.update(status=status, response=json.dumps(redact(response)))
            self._finish(key, 'done', saved)
            return status, redact(response)

    def _finish(self, key, status, body):
        self.db.conn.execute("UPDATE records SET status=?,body=?,updated_at=? WHERE kind='api_request' AND id=? AND revision=0",
                             (status, json.dumps(body), _now(), key))

    def run(self, key, method, path, body, fn):
        fingerprint = request_hash(method, path, body)
        with self.db.uow() as u:
            row = u.records.get('api_request', key)
            if row:
                saved = json.loads(row['body'])
                if saved['request_hash'] != fingerprint:
                    raise ContractError('idempotency_conflict', 'Idempotency-Key', 'key reused with a different request')
                if row['status'] == 'done':
                    return saved['status'], json.loads(saved['response'])
                if row['status'] == 'rejected':
                    raise ContractError(**saved['error'])
                raise ContractError('idempotency_unresolved', 'Idempotency-Key', 'inspect the durable action before retrying')
            saved = {'request_hash': fingerprint, 'method': method, 'path': path}
            u.conn.execute("INSERT INTO records(kind,id,revision,schema_version,status,body,created_at,updated_at) VALUES('api_request',?,0,'api_request.v2','in_progress',?,?,?)",
                           (key, json.dumps(saved), _now(), _now()))
        try:
            status, response = fn()
        except ContractError as error:
            saved['error'] = {'code': error.code, 'field': error.field, 'detail': redact(error.detail)}
            self._finish_external(key, 'rejected', saved)
            raise
        except Exception:
            self._finish_external(key, 'unknown', saved)
            raise
        saved.update(status=status, response=json.dumps(redact(response)))
        self._finish_external(key, 'done', saved)
        return status, redact(response)

    def _finish_external(self,key,status,body):
        with self.db.uow():
            self._finish(key,status,body)
