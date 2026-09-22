"""Reversible dashboard preferences, never execution or accounting cleanup.

Markers bind to the exact terminal record version. Reopened/changed work is
visible again, and eligibility is rechecked under the archive transaction.
"""
import hashlib
import json

from ..domain.errors import ContractError
from ..store.uow import utcnow


PREFIX = 'dashboard:archive:'
TERMINAL = {'succeeded', 'failed', 'cancelled'}
FINISHED_ATTEMPTS = {'succeeded', 'failed', 'cancelled', 'downloaded'}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


class DashboardHistory:
    def __init__(self, db):
        self.db = db

    def snapshot(self):
        # One read snapshot, including when nested in the write transaction.
        with self.db.uow() as u:
            return self._snapshot(u.conn)

    def _snapshot(self, conn):
        jobs = {r['id']: dict(r) for r in conn.execute('SELECT * FROM jobs')}
        runs = {r['id']: dict(r) for r in conn.execute(
            "SELECT * FROM records r WHERE kind='autorun' AND revision="
            "(SELECT MAX(revision) FROM records x WHERE x.kind=r.kind AND x.id=r.id)")}
        bodies = {rid: json.loads(r['body']) for rid, r in runs.items()}
        members = {rid: set(_strings(body)) & jobs.keys() for rid, body in bodies.items()}
        for command in conn.execute("SELECT id,body FROM records WHERE kind='appcommand'"):
            for rid in set(_strings(json.loads(command['body']))) & runs.keys():
                if command['id'] in jobs:
                    members[rid].add(command['id'])
        groups = {}
        for jid, job in jobs.items():
            if job['experiment_id']:
                groups.setdefault(job['experiment_id'], set()).add(jid)
        for rid, body in bodies.items():
            eid = body.get('experiment_id') or body.get('state', {}).get('experiment_id')
            members[rid].update(groups.get(eid, set()))

        protected = {jid for jid, j in jobs.items() if j['status'] not in TERMINAL}
        protected.update(r['job_id'] for r in conn.execute('SELECT job_id,status FROM attempts')
                         if r['status'] not in FINISHED_ATTEMPTS)
        protected.update(r['job_id'] for r in conn.execute(
            "SELECT job_id FROM capacity_holds WHERE expires_at>? OR "
            "retained_reason IN ('unfinished_remote_op','unfinished_local_work')", (utcnow(),)))
        protected_runs = {rid for rid, r in runs.items() if r['status'] not in TERMINAL}
        # Keep an ongoing run/experiment and its dependency evidence together.
        while True:
            before = (len(protected), len(protected_runs))
            for group in groups.values():
                if group & protected:
                    protected.update(group)
            for rid, group in members.items():
                if rid in protected_runs or group & protected:
                    protected_runs.add(rid)
                    protected.update(group)
            for jid in list(protected & jobs.keys()):
                protected.update(json.loads(jobs[jid]['depends_on']))
            if before == (len(protected), len(protected_runs)):
                break

        markers = {r['key']: r['value'] for r in conn.execute(
            'SELECT key,value FROM meta WHERE key LIKE ?', (PREFIX + '%',))}
        items = []
        for kind, rows, blocked in (('job', jobs, protected), ('run', runs, protected_runs)):
            for rid, row in rows.items():
                version_hash = hashlib.sha256(json.dumps(
                    [row['status'], row['version'], row['updated_at']],
                    separators=(',', ':')).encode()).hexdigest()
                eligible = rid not in blocked
                items.append({'kind': kind, 'id': rid, 'version_hash': version_hash,
                              'status': row['status'], 'eligible': eligible,
                              'archived': eligible and markers.get(PREFIX + kind + ':' + rid) == version_hash})
        return {'items': items}

    def update(self, body):
        action, targets = body.get('action'), body.get('targets')
        if action not in ('archive', 'restore') or not isinstance(targets, list) or not targets:
            raise ContractError('invalid_history_action', 'action/targets', 'Select history to archive or restore.')
        if any(not isinstance(t, dict) or t.get('kind') not in ('job', 'run')
               or not isinstance(t.get('id'), str) or not isinstance(t.get('version_hash'), str) for t in targets):
            raise ContractError('invalid_history_action', 'targets', 'Invalid history selection.')
        with self.db.uow() as u:
            current = {(i['kind'], i['id']): i for i in self._snapshot(u.conn)['items']}
            selected = {(t['kind'], t['id']): t for t in targets}
            for identity, target in selected.items():
                item = current.get(identity)
                if not item or item['version_hash'] != target['version_hash'] or (action == 'archive' and not item['eligible']):
                    raise ContractError('stale_revision', 'history',
                                        'Work changed since the preview. Reopen Clean up to refresh it; nothing was hidden.')
            for (kind, rid), target in selected.items():
                key = PREFIX + kind + ':' + rid
                if action == 'archive':
                    u.conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                   (key, target['version_hash']))
                else:
                    # Only our UI preference is removed, never a job or file.
                    u.conn.execute('DELETE FROM meta WHERE key=?', (key,))
            counts = {kind: sum(k == kind for k, _ in selected) for kind in ('job', 'run')}
            u.events.append('factory', 'dashboard_history_' + action, counts)
        return {'action': action, 'counts': counts}
