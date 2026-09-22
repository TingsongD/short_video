"""Run-owned immutable evidence with bounded, restart-safe local checkpoints.

This module never calls a provider. Blob references are relative, hash-bound,
and independent of the media registry. Historical bundles are never replaced.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from ..domain.errors import ContractError
from ..domain.records import Record, content_hash
from ..store.uow import utcnow


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@dataclass
class SourceEvidence(Record):
    status: str = 'processing'
    run_id: str = ''
    binding: dict = field(default_factory=dict)
    policy: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)
    executions: int = 0
    analysis_plan: dict = field(default_factory=dict)
    analysis_requests: list = field(default_factory=list)


@dataclass
class SourceEvidenceChunk(Record):
    status: str = 'processing'
    evidence_id: str = ''
    stage: str = ''
    start: int = 0
    end: int = 0
    attempts: int = 0
    blob: dict = field(default_factory=dict)
    error: str = ''
    lease: dict = field(default_factory=dict)


class EvidenceBlobs:
    def __init__(self, root, *, max_bytes=32*1024**3):
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes

    def disk_bytes(self):
        total = 0
        for base, directories, files in os.walk(self.root, followlinks=False):
            for name in directories+files:
                path = Path(base)/name
                if path.is_symlink():
                    raise ContractError('evidence_path_escape', 'disk_accounting')
                if name in files:
                    try:
                        total += path.stat().st_size
                    except FileNotFoundError:
                        pass  # An owned temporary audio file may have completed.
        return total

    def put(self, value):
        data = _bytes(value)
        digest = hashlib.sha256(data).hexdigest()
        target = self.root / 'blobs' / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.resolve().is_relative_to(self.root):
            raise ContractError('evidence_path_escape', 'blob')
        if target.exists():
            self.read({'sha256': digest, 'bytes': len(data)})
        else:
            if len(data)+self.disk_bytes() > self.max_bytes:
                raise ContractError('source_evidence_disk_limit', 'blob', 'Preserve referenced evidence; free space through reviewed retention.')
            fd, name = tempfile.mkstemp(prefix='.staged-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
                # Link is an atomic create, never an overwrite of prior evidence.
                try:
                    os.link(name, target)
                except FileExistsError:
                    self.read({'sha256': digest, 'bytes': len(data)})
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                os.unlink(name)
        return {'sha256': digest, 'bytes': len(data)}

    def read(self, reference):
        digest = reference.get('sha256', '')
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ContractError('invalid_evidence_reference', 'sha256')
        path = self.root / 'blobs' / digest[:2] / digest
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ContractError('evidence_path_escape', 'blob')
        try:
            data = path.read_bytes()
        except OSError:
            raise ContractError('evidence_unavailable', 'blob', digest) from None
        if len(data) != reference.get('bytes') or hashlib.sha256(data).hexdigest() != digest:
            raise ContractError('evidence_hash_mismatch', 'blob', digest)
        return json.loads(data)


class SourceEvidenceService:
    def __init__(self, db, root, *, verify_lease=None, current_binding=None):
        self.db, self.blobs = db, EvidenceBlobs(root)
        self.verify_lease, self.current_binding = verify_lease, current_binding

    def create(self, run_id, binding, policy):
        required = {'seed_id', 'seed_revision', 'source_artifact_id', 'source_sha256',
                    'analysis_revision', 'transcript_sha256', 'edit_token'}
        if not required <= set(binding):
            raise ContractError('incomplete_source_binding', 'binding')
        for key in ('source_sha256', 'transcript_sha256', 'edit_token'):
            if not re.fullmatch('[a-f0-9]{64}', binding[key]):
                raise ContractError('invalid_source_binding', key)
        _bytes([binding, policy])
        ident = 'evidence-' + content_hash([run_id, binding, policy])[:32]
        with self.db.uow() as u:
            prior = u.records.get('sourceevidence', ident)
            if prior:
                return json.loads(prior['body'])
            record = SourceEvidence(schema_version='source_evidence.v1', id=ident,
                                    created_at=utcnow(), run_id=run_id, binding=binding, policy=policy)
            u.records.put(record)
        return record.to_dict()

    def get(self, evidence_id):
        row = self.db.uow().records.get('sourceevidence', evidence_id)
        if not row:
            raise ContractError('not_found', 'source_evidence', evidence_id)
        return json.loads(row['body'])

    def _guard(self, u, record, supplied_binding, lease):
        current = self.current_binding(record['run_id']) if self.current_binding else supplied_binding
        if current != record['binding']:
            raise ContractError('source_evidence_stale', 'binding')
        if self.verify_lease:
            if not lease:
                raise ContractError('source_evidence_lease_required', 'job')
            self.verify_lease(u, lease['job_id'], lease['fencing_token'])

    def chunk(self, evidence_id, stage, start, end, produce, *, current_binding=None, lease=None):
        if stage not in ('clock', 'visual', 'audio', 'fusion', 'media') or any(type(x) is not int for x in (start, end)) or not 0 <= start < end:
            raise ContractError('invalid_evidence_chunk', 'range')
        record = self.get(evidence_id)
        ident = 'evchunk-' + content_hash([evidence_id, stage, start, end])[:32]
        with self.db.uow() as u:
            self._guard(u, record, current_binding, lease)
            row = u.records.get('sourceevidencechunk', ident)
            chunk = SourceEvidenceChunk(**json.loads(row['body'])) if row else SourceEvidenceChunk(
                schema_version='source_evidence_chunk.v1', id=ident, created_at=utcnow(),
                evidence_id=evidence_id, stage=stage, start=start, end=end)
            if chunk.status == 'complete':
                return {**chunk.blob, 'data': self.blobs.read(chunk.blob), 'reused': True}
            if record['status'] == 'complete':
                raise ContractError('evidence_already_complete', stage)
            if chunk.attempts >= 3:
                raise ContractError('source_evidence_repair_exhausted', stage, f'{start}:{end}')
            if row and chunk.status == 'processing' and chunk.lease == (lease or {}):
                raise ContractError('source_evidence_chunk_inflight', stage, f'{start}:{end}')
            chunk.attempts += 1
            chunk.status, chunk.error, chunk.lease = 'processing', '', lease or {}
            u.records.put(chunk, expected_version=row['version'] if row else None)
            version = (row['version'] + 1) if row else 1
        try:
            result = produce()
            blob = self.blobs.put(result)
        except Exception as error:
            with self.db.uow() as u:
                self._guard(u, record, current_binding, lease)
                chunk.status = 'failed'
                chunk.error = error.code if isinstance(error, ContractError) else type(error).__name__
                u.records.put(chunk, expected_version=version)
            raise
        with self.db.uow() as u:
            self._guard(u, record, current_binding, lease)
            chunk.status, chunk.blob = 'complete', blob
            u.records.put(chunk, expected_version=version)
        return {**blob, 'data': result, 'reused': False}

    def chunks(self, evidence_id, stage=None):
        self.get(evidence_id)
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='sourceevidencechunk' "
            "AND json_extract(body,'$.evidence_id')=?", (evidence_id,)).fetchall()
        chunks = [json.loads(row[0]) for row in rows]
        return sorted((c for c in chunks if stage is None or c['stage'] == stage),
                      key=lambda c: (c['stage'], c['start'], c['end']))

    def complete(self, evidence_id, totals, *, current_binding=None, lease=None):
        stages={'clock', 'visual', 'audio', 'fusion'}
        if set(totals) not in (stages, stages|{'media'}) or any(type(x) is not int or x <= 0 for x in totals.values()):
            raise ContractError('invalid_evidence_coverage', 'totals')
        with self.db.uow() as u:
            row = u.records.get('sourceevidence', evidence_id)
            record = self.get(evidence_id)
            self._guard(u, record, current_binding, lease)
            if record['policy'].get('version')=='flashcut_policy.v1' and 'media' not in totals:
                raise ContractError('coverage_incomplete','selected_media')
            if record['status'] == 'complete':
                manifest = self.blobs.read(record['manifest'])
                if manifest['totals'] != totals:
                    raise ContractError('evidence_identity_conflict', 'totals')
                return record
            chunks = self.chunks(evidence_id)
            for stage, total in totals.items():
                cursor = 0
                for chunk in (c for c in chunks if c['stage'] == stage):
                    if chunk['status'] != 'complete' or chunk['start'] != cursor:
                        raise ContractError('coverage_incomplete', stage, f'position {cursor}')
                    self.blobs.read(chunk['blob'])
                    cursor = chunk['end']
                if cursor != total:
                    raise ContractError('coverage_incomplete', stage, f'{cursor}/{total}')
            manifest = {'schema_version': 'source_evidence_manifest.v1',
                        'evidence_id':evidence_id,'run_id':record['run_id'],
                        'binding': record['binding'], 'policy': record['policy'],
                        'totals': totals, 'chunks': [{k: c[k] for k in
                            ('stage', 'start', 'end', 'blob')} for c in chunks]}
            updated = SourceEvidence(**record)
            updated.manifest = self.blobs.put(manifest)
            updated.status = 'complete'
            u.records.put(updated, expected_version=row['version'])
            return updated.to_dict()

    def manifest(self, evidence_id):
        record = self.get(evidence_id)
        if record['status'] != 'complete':
            raise ContractError('coverage_incomplete', 'source_evidence')
        return self.blobs.read(record['manifest'])

    def report_progress(self, evidence_id, values, *, current_binding=None, lease=None):
        allowed = {'stage', 'decoded_frames', 'encoded_frames', 'total_frames', 'processed_audio_samples',
                   'total_audio_samples', 'audio_status', 'rhythm_status', 'cache_reused_chunks', 'event_count'}
        if set(values) - allowed:
            raise ContractError('invalid_evidence_progress', 'progress')
        with self.db.uow() as u:
            row = u.records.get('sourceevidence', evidence_id)
            record = self.get(evidence_id)
            self._guard(u, record, current_binding, lease)
            updated = SourceEvidence(**record)
            updated.progress.update(values, updated_at=utcnow())
            u.records.put(updated, expected_version=row['version'])

    def start_execution(self, evidence_id, *, current_binding=None, lease=None):
        """Bound failures outside individual chunks (startup, extraction, OOM)."""
        with self.db.uow() as u:
            row = u.records.get('sourceevidence', evidence_id)
            record = self.get(evidence_id)
            self._guard(u, record, current_binding, lease)
            if record['status'] == 'complete':
                raise ContractError('evidence_already_complete', 'helper')
            updated = SourceEvidence(**record)
            if updated.executions >= 3:
                raise ContractError('source_evidence_repair_exhausted', 'helper',
                                    'Initial execution and two local recoveries exhausted; inspect source and helper diagnostics.')
            updated.executions += 1
            u.records.put(updated, expected_version=row['version'])
            return updated.executions


def binding_from_db(db, run_id):
    """Recheck actual current records, never trust a helper's copied token."""
    run_row = db.uow().records.get('autorun', run_id)
    if not run_row:
        raise ContractError('not_found', 'autorun')
    run = json.loads(run_row['body'])
    seed_row = db.uow().records.get('seed', run['seed_id'])
    analysis_row = db.uow().records.get('referenceanalysis', 'ra-'+run['seed_id'])
    if not seed_row or not analysis_row:
        raise ContractError('analysis_evidence_unavailable', 'binding')
    seed, analysis = json.loads(seed_row['body']), json.loads(analysis_row['body'])
    artifact = db.uow().artifacts.get(seed['source_asset_id'])
    if not artifact or artifact['sha256'] != analysis['source_sha256']:
        raise ContractError('source_evidence_stale', 'source_sha256')
    transcript = analysis['transcript']
    transcript_hash = transcript.get('sha256') or analysis.get('documents', {}).get('hashes', {}).get('transcript_json')
    if not transcript_hash:
        if transcript.get('status') not in ('not_applicable', 'declared_nonverbal'):
            raise ContractError('analysis_evidence_unavailable', 'transcript_sha256')
        transcript_hash = content_hash(['no_speech', transcript['status'], artifact['sha256']])
    return {'seed_id': seed['id'], 'seed_revision': seed['revision'], 'source_artifact_id': artifact['id'],
            'source_sha256': artifact['sha256'], 'analysis_revision': analysis['revision'],
            'transcript_sha256': transcript_hash,
            'edit_token': content_hash({'seed_id': seed['id'], 'source_sha256': artifact['sha256'],
                                       'revision': analysis['revision'], 'version': analysis_row['version']})}
