"""Durable evidence interface: isolated database, no provider or model download."""
import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.store import Database


def binding():
    return dict(seed_id='seed-test', seed_revision=1, source_artifact_id='art-test',
                source_sha256='a'*64, analysis_revision=1, transcript_sha256='b'*64,
                edit_token='c'*64)


def test_completed_chunk_is_reused_after_restart_and_cannot_be_rebound(tmp_path):
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    db = Database(tmp_path/'test.db')
    try:
        evidence = SourceEvidenceService(db, tmp_path/'evidence')
        record = evidence.create('run-test', binding(), {'version': 'test.v1'})
        result = evidence.chunk(record['id'], 'visual', 0, 2,
            lambda: {'frame_count': 2, 'clean_decode': False}, current_binding=binding())
        assert result['data']['frame_count'] == 2
        restored = SourceEvidenceService(db, tmp_path/'evidence')
        def forbidden():
            pytest.fail('A completed immutable chunk must not be computed again')
        reused = restored.chunk(record['id'], 'visual', 0, 2, forbidden, current_binding=binding())
        assert reused['reused'] and reused['sha256'] == result['sha256']
        with pytest.raises(ContractError, match='source_evidence_stale'):
            restored.chunk(record['id'], 'visual', 0, 2, forbidden,
                           current_binding={**binding(), 'analysis_revision': 2})
    finally:
        db.close()


def test_local_repair_limit_survives_restart(tmp_path):
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    db = Database(tmp_path/'test.db')
    try:
        evidence = SourceEvidenceService(db, tmp_path/'evidence')
        record = evidence.create('run-test', binding(), {'version': 'test.v1'})
        calls = []
        def broken():
            calls.append(1)
            raise ContractError('decode_failed', 'frames')
        for _ in range(3):
            evidence = SourceEvidenceService(db, tmp_path/'evidence')
            with pytest.raises(ContractError, match='decode_failed'):
                evidence.chunk(record['id'], 'visual', 0, 2, broken, current_binding=binding())
        with pytest.raises(ContractError, match='source_evidence_repair_exhausted'):
            SourceEvidenceService(db, tmp_path/'evidence').chunk(
                record['id'], 'visual', 0, 2, broken, current_binding=binding())
        assert len(calls) == 3
    finally:
        db.close()


def test_late_result_cannot_publish_after_source_edit(tmp_path):
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    db = Database(tmp_path/'test.db')
    current = binding()
    try:
        evidence = SourceEvidenceService(db, tmp_path/'evidence', current_binding=lambda _: current)
        record = evidence.create('run-test', binding(), {'version': 'test.v1'})
        def late():
            current['analysis_revision'] = 2
            return {'frame_count': 2}
        with pytest.raises(ContractError, match='source_evidence_stale'):
            evidence.chunk(record['id'], 'visual', 0, 2, late)
        assert evidence.get(record['id'])['manifest'] == {}
    finally:
        db.close()


def test_tampered_checkpoint_is_unavailable_not_recomputed(tmp_path):
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    db = Database(tmp_path/'test.db')
    try:
        evidence = SourceEvidenceService(db, tmp_path/'evidence')
        record = evidence.create('run-test', binding(), {'version': 'test.v1'})
        result = evidence.chunk(record['id'], 'visual', 0, 2, lambda: {'frame_count': 2}, current_binding=binding())
        blob = tmp_path/'evidence/blobs'/result['sha256'][:2]/result['sha256']
        blob.write_text('{}')
        with pytest.raises(ContractError, match='evidence_hash_mismatch'):
            evidence.chunk(record['id'], 'visual', 0, 2, lambda: pytest.fail('must not overwrite'), current_binding=binding())
    finally:
        db.close()


def test_manifest_requires_complete_contiguous_chunks(tmp_path):
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    db = Database(tmp_path/'test.db')
    try:
        evidence = SourceEvidenceService(db, tmp_path/'evidence')
        record = evidence.create('run-test', binding(), {'version': 'test.v1'})
        for stage in ('clock', 'audio', 'fusion'):
            evidence.chunk(record['id'], stage, 0, 1, lambda: {'status': 'ok'}, current_binding=binding())
        with pytest.raises(ContractError, match='coverage_incomplete'):
            evidence.complete(record['id'], {'clock':1, 'visual':2, 'audio':1, 'fusion':1}, current_binding=binding())
        evidence.chunk(record['id'], 'visual', 0, 2, lambda: {'frame_count': 2}, current_binding=binding())
        result = evidence.complete(record['id'], {'clock':1, 'visual':2, 'audio':1, 'fusion':1}, current_binding=binding())
        assert result['status'] == 'complete' and result['manifest']['sha256']
        assert evidence.manifest(record['id'])['binding'] == binding()
        with pytest.raises(ContractError, match='evidence_already_complete'):
            evidence.chunk(record['id'], 'visual', 2, 3, lambda: {}, current_binding=binding())
    finally:
        db.close()


def test_helper_attempt_limit_and_stale_lease_survive_restart(tmp_path):
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    db = Database(tmp_path/'test.db')
    fence = [1]
    def verify(u, job_id, token):
        if token != fence[0]:
            raise ContractError('stale_fencing', 'helper')
    try:
        for index in range(3):
            service = SourceEvidenceService(db, tmp_path/'evidence', verify_lease=verify)
            record = service.create('run-test', binding(), {'version': 'test.v1'})
            assert service.start_execution(record['id'], current_binding=binding(),
                    lease={'job_id': 'job', 'fencing_token': fence[0]}) == index+1
            fence[0] += 1
        with pytest.raises(ContractError, match='stale_fencing'):
            service.start_execution(record['id'], current_binding=binding(), lease={'job_id':'job', 'fencing_token':1})
        with pytest.raises(ContractError, match='source_evidence_repair_exhausted'):
            service.start_execution(record['id'], current_binding=binding(), lease={'job_id':'job', 'fencing_token':4})
    finally:
        db.close()


def test_disk_budget_refuses_new_blob_without_overwriting_valid_cache(tmp_path):
    from modules.factory.analysis.source_evidence import EvidenceBlobs
    blobs = EvidenceBlobs(tmp_path/'store', max_bytes=16)
    first = blobs.put({'a':1})
    with pytest.raises(ContractError, match='source_evidence_disk_limit'):
        blobs.put({'large':'01234567890123456789'})
    assert blobs.put({'a':1}) == first and blobs.read(first) == {'a':1}
