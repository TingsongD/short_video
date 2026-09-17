"""Durable, local application commands. External effects run only in workers."""
import json
import uuid
from ..domain.records import Job
from ..domain.errors import ContractError
from ..events.redact import redact
from ..store.uow import utcnow


class CommandQueue:
    def __init__(self, db, scheduler):
        self.db, self.scheduler = db, scheduler

    def enqueue(self, kind, body, *, experiment_id='', revision=0, phase='plan', depends=(), identity=None):
        jid = identity or f'cmd-{uuid.uuid4().hex}'
        with self.db.uow() as u:
            prior = u.records.get('appcommand', jid)
            if prior:
                saved = json.loads(prior['body'])
                if saved['kind'] != kind or saved['input'] != body:
                    raise ContractError('command_identity_conflict', 'command')
                return {'job_id': jid, 'accepted': True}
            if redact(body) != body:
                raise ContractError('sensitive_request', 'command')
            data = {'id': jid, 'kind': kind, 'input': body, 'result': None}
            u.conn.execute("INSERT INTO records(kind,id,revision,schema_version,status,body,created_at,updated_at) VALUES('appcommand',?,0,'appcommand.v1','queued',?,?,?)",
                           (jid, json.dumps(data), utcnow(), utcnow()))
            self.scheduler.submit_plan([Job(schema_version='job.v1', id=jid, created_at=utcnow(),
                logical_key=jid, phase=phase, experiment_id=experiment_id, revision=revision,
                depends_on=list(depends))])
            u.events.append('factory', 'command_queued', {'job_id': jid, 'kind': kind})
        return {'job_id': jid, 'accepted': True}

    def get(self, jid):
        row = self.db.uow().records.get('appcommand', jid)
        job = self.db.uow().jobs.get(jid)
        if not job:
            raise ContractError('not_found', 'job_id', jid)
        return {**job, 'command': json.loads(row['body']) if row else None}

    def finish(self, jid, result):
        with self.db.uow() as u:
            row = u.records.get('appcommand', jid)
            if row:
                body = json.loads(row['body']); body['result'] = redact(result)
                u.conn.execute("UPDATE records SET body=?,status='done',updated_at=? WHERE kind='appcommand' AND id=?", (json.dumps(body), utcnow(), jid))
            u.events.append('factory', 'command_finished', {'job_id': jid, 'result': result})
