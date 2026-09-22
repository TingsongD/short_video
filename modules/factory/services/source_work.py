"""Queue-owned, credential-free dense source analysis; no hosted effects."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from ..analysis.evidence_policy import validate_flashcut_policy
from ..analysis.source_evidence import binding_from_db
from ..domain.errors import ContractError
from ..resources.runner import OwnedRunner
from ...batch.local import process_table, same_process


class SourceEvidenceWork:
    def __init__(self, services, repo, *, runner=None, free_bytes=None, owned_alive=None):
        self.s, self.repo, self.runner = services, Path(repo).resolve(), runner
        self.free_bytes = free_bytes or (lambda path: shutil.disk_usage(path).free)
        self.owned_alive = owned_alive or self._owned_alive

    def _owned_alive(self, owner):
        owned = self.s.resources.for_owner(owner)
        if not owned:
            return False
        table = process_table()  # Inspection failure must not mean no process.
        return any(same_process(item, table.get(item['pid'])) for item in owned)

    def prepare(self, run_id, policy):
        policy = validate_flashcut_policy(policy)
        binding = binding_from_db(self.s.db, run_id)
        analysis = self.s.ref_analysis.get(binding['seed_id'])
        if analysis.transcript.get('status') not in ('not_applicable', 'declared_nonverbal'):
            self.s.ref_analysis.verified_transcript(analysis)
        self.s.artifacts.verified_path(binding['source_artifact_id'])
        record = self.s.source_evidence.create(run_id, binding, policy)
        queued = self.s.commands.enqueue('source_evidence', {'evidence_id': record['id']},
                         phase='analyze_dense', identity=record['id']+':analyze')
        return {**queued, 'evidence_id': record['id']}

    def execute(self, body, job):
        evidence = self.s.source_evidence
        record = evidence.get(body['evidence_id'])
        policy = validate_flashcut_policy(record['policy'])
        lease = {'job_id': job['id'], 'fencing_token': job['fencing_token']}
        with self.s.db.uow() as u:
            evidence._guard(u, record, None, lease)
        if record['status'] == 'complete':
            evidence.manifest(record['id'])
            self._clear(job)
            return {'status': 'complete', 'evidence_id': record['id'], 'manifest': record['manifest']}
        root = evidence.blobs.root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.free_bytes(root) < policy['resources']['min_free_bytes']:
            raise ContractError('source_evidence_disk_full', 'source_evidence', 'At least 10 GiB free space required.')
        owner = 'source-evidence:'+record['id']
        try:
            if self.owned_alive(owner):
                return {'status': 'pending', 'reason': 'helper_observation', 'defer_s': 5}
        except (OSError, subprocess.SubprocessError, ContractError):
            return {'status': 'pending', 'reason': 'helper_process_inspection_unavailable', 'defer_s': 30}
        python = self.repo/'vendor/flashcut-helper/.venv/bin/python'
        if not python.is_file():
            raise ContractError('source_helper_not_installed', 'helper', 'Run the explicit offline helper setup first.')
        key = 'local_work:'+job['id']
        with self.s.db.uow() as u:
            prior = u.conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            if prior:
                intent = json.loads(prior[0])
                if intent.get('evidence_id') != record['id']:
                    raise ContractError('evidence_identity_conflict', 'helper_intent')
            else:
                attempt = evidence.start_execution(record['id'], lease=lease)
                request = {'version': 'flashcut_helper.v1', 'database': str(self.s.db.path),
                           'evidence_id': record['id'], **lease, 'lease_owner': job['lease_owner']}
                directory = root/'requests'/record['id']
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, path = tempfile.mkstemp(prefix=f'{attempt}-', suffix='.json', dir=directory)
                with os.fdopen(fd, 'w') as file:
                    json.dump(request, file, sort_keys=True)
                    file.flush()
                    os.fsync(file.fileno())
                intent = {'kind': 'source_evidence', 'evidence_id': record['id'], 'attempt': attempt, 'request': path,
                          'request_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                u.conn.execute('INSERT INTO meta(key,value) VALUES(?,?)', (key, json.dumps(intent)))
        request_path = Path(intent['request'])
        if not request_path.resolve().is_relative_to(root) or request_path.is_symlink():
            raise ContractError('restored_source_work_requires_rebind', 'helper_intent',
                                'Keep checkpoints; reconcile the restored local job before creating a new helper intent.')
        if hashlib.sha256(request_path.read_bytes()).hexdigest() != intent.get('request_sha256'):
            raise ContractError('evidence_hash_mismatch', 'helper_request')
        runner = self.runner or OwnedRunner(self.s.db, root/'processes'/record['id'], owner,
            attempt=intent['attempt'], environment={
                'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8',
                'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4',
                'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'})
        try:
            result = runner([str(python), '-m', 'modules.factory.analysis.local_helper', intent['request']],
                            cwd=self.repo, timeout=7200)
        except (subprocess.TimeoutExpired, ContractError) as error:
            if isinstance(error, ContractError) and error.code != 'local_process_unresolved':
                raise
            return {'status': 'pending', 'reason': 'helper_observation', 'defer_s': 5}
        # A durable supervisor receipt establishes this process has exited.
        self._clear(job)
        current = evidence.get(record['id'])
        if result.returncode == 0 and current['status'] == 'complete':
            evidence.manifest(record['id'])
            return {'status': 'complete', 'evidence_id': record['id'], 'manifest': current['manifest']}
        error = 'source_helper_failed'
        try:
            report = json.loads(result.stdout.strip().splitlines()[-1])
            if isinstance(report.get('error'), str) and report['error'].replace('_', '').isalnum():
                error = report['error']
        except (ValueError, IndexError, AttributeError):
            pass
        recoverable = error in ('source_helper_failed', 'helper_failed', 'resource_limit_exhausted',
                                'source_evidence_no_progress', 'decode_failed')
        if not recoverable or intent['attempt'] >= 3:
            failed = [c for c in evidence.chunks(record['id']) if c['status'] != 'complete']
            ranges = ', '.join(f"{c['stage']} {c['start']}:{c['end']}" for c in failed)
            raise ContractError(error, 'source_evidence',
                                f"{record['id']}: {ranges or 'helper startup/extraction'}. "
                                'Source analysis stopped; inspect local evidence diagnostics. No paid work was submitted.')
        return {'status': 'pending',
                'reason': error, 'error': error, 'evidence_id': record['id'],
                'repairs_used': max(0, intent['attempt']-1), 'defer_s': 5}

    def _clear(self, job):
        with self.s.db.uow() as u:
            u.conn.execute('DELETE FROM meta WHERE key=?', ('local_work:'+job['id'],))
