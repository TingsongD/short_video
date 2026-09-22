"""Unpaid source work is serialized and never duplicates a surviving helper."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest

from modules.factory.bootstrap import bootstrap
from modules.factory.analysis.source_evidence import SourceEvidenceService
from modules.factory.analysis.evidence_policy import new_flashcut_policy
from modules.factory.domain.errors import ContractError
from test_factory_source_evidence import binding


def test_unavailable_disk_inspection_is_a_failure_not_unmonitored_processing(tmp_path,monkeypatch):
    from modules.factory.analysis.local_helper import storage_problem
    def unavailable(_):raise OSError('disk inspection unavailable')
    monkeypatch.setattr('shutil.disk_usage',unavailable)
    assert storage_problem(tmp_path,[tmp_path],new_flashcut_policy()['resources'])=='source_evidence_storage_unavailable'


def test_selected_media_storage_is_counted_alongside_evidence(tmp_path):
    from modules.factory.analysis.local_helper import storage_problem
    images=tmp_path/'artifacts';images.mkdir();(images/'frame.png').write_bytes(b'x'*30)
    evidence=tmp_path/'evidence';evidence.mkdir();(evidence/'chunk.json').write_bytes(b'x'*10)
    limits={**new_flashcut_policy()['resources'],'min_free_bytes':0,'max_disk_bytes':32}
    assert storage_problem(tmp_path,[evidence,images],limits)=='source_evidence_disk_limit'


def test_actual_helper_job_publishes_fenced_all_frame_evidence(tmp_path):
    """Real Python 3.11 process, installed PE, local media, zero network."""
    from modules.factory.autorun.service import AutoRun
    from modules.factory.services.worker import ApplicationWorker
    from modules.factory.store.uow import utcnow
    from test_factory_application import seed_completed_analysis
    s = bootstrap(tmp_path)
    try:
        clip = tmp_path/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=72x128:r=30:d=0.2',
                        '-an','-c:v','libx264',str(clip)], check=True)
        artifact = s.artifacts.intake_file(clip, 'seed_source', 'flashcut-local')
        seed, _ = s.seeds.submit_url('https://www.youtube.com/shorts/cliptest001')
        seed, _ = s.seeds.attach_media(seed.id, artifact.id)
        analysis = seed_completed_analysis(s.db, seed.id, artifact.sha256, duration_s=0.2)
        analysis.transcript = {'status':'not_applicable'}
        with s.db.uow() as u:
            row = u.records.get('referenceanalysis', analysis.id)
            u.records.put(analysis, expected_version=row['version'])
            u.records.put(AutoRun(schema_version='autorun.v1', id='run-flashcut-local', created_at=utcnow(), seed_id=seed.id))
        prepared = s.source_work.prepare('run-flashcut-local', new_flashcut_policy())
        result = ApplicationWorker(s).tick()
        assert result['status'] == 'complete', result
        manifest = s.source_evidence.manifest(prepared['evidence_id'])
        assert manifest['totals']['visual'] == 6
        assert s.commands.get(prepared['job_id'])['status'] == 'succeeded'
        assert not s.db.conn.execute('SELECT * FROM capacity_holds').fetchall()
    finally:
        s.db.close()


def test_owned_helper_environment_excludes_host_credentials(tmp_path, monkeypatch):
    from modules.factory.resources.runner import OwnedRunner
    import sys
    s = bootstrap(tmp_path)
    try:
        monkeypatch.setenv('FACTORY_TEST_SECRET', 'must-not-be-in-child')
        runner = OwnedRunner(s.db, tmp_path/'runner', 'offline-test', environment={'PATH':'/usr/bin:/bin','LANG':'C'})
        result = runner([sys.executable, '-c', 'import os; print("FACTORY_TEST_SECRET" in os.environ)'], timeout=10)
        assert result.returncode == 0 and result.stdout.strip() == 'False'
    finally:
        s.db.close()


def test_local_media_retains_capacity_until_owned_work_resolved(tmp_path):
    s = bootstrap(tmp_path)
    try:
        first = s.commands.enqueue('source_evidence', {}, phase='analyze_dense')['job_id']
        second = s.commands.enqueue('source_evidence', {}, phase='analyze_dense')['job_id']
        job = s.scheduler.claim()
        assert job['id'] == first
        with s.db.uow() as u:
            u.conn.execute('INSERT INTO meta(key,value) VALUES(?,?)', ('local_work:'+first, '{}'))
        s.scheduler.defer(first, job['fencing_token'], 'helper_observation', 600)
        assert s.scheduler.claim() is None
        hold = s.db.conn.execute('SELECT capacity,retained_reason FROM capacity_holds WHERE job_id=?', (first,)).fetchone()
        assert tuple(hold) == ('local_media', 'unfinished_local_work')
    finally:
        s.db.close()


def test_disk_admission_and_existing_child_prevent_launch(tmp_path):
    from modules.factory.services.source_work import SourceEvidenceWork
    s = bootstrap(tmp_path)
    try:
        s.source_evidence = SourceEvidenceService(s.db, tmp_path/'evidence', current_binding=lambda _: binding())
        record = s.source_evidence.create('run', binding(), new_flashcut_policy())
        calls = []
        runner = lambda *a, **kw: calls.append(a)
        work = SourceEvidenceWork(s, Path(__file__).resolve().parents[1],
                                  runner=runner, free_bytes=lambda _: 0, owned_alive=lambda _: False)
        queued = s.commands.enqueue('source_evidence', {'evidence_id': record['id']}, phase='analyze_dense')
        job = s.scheduler.claim()
        with pytest.raises(ContractError, match='source_evidence_disk_full'):
            work.execute({'evidence_id': record['id']}, job)
        assert calls == []
        work.free_bytes = lambda _: 100*1024**3
        work.owned_alive = lambda _: True
        assert work.execute({'evidence_id': record['id']}, job)['status'] == 'pending'
        assert calls == []
    finally:
        s.db.close()


def test_helper_failure_retries_are_persisted_and_request_is_versioned(tmp_path):
    from modules.factory.services.source_work import SourceEvidenceWork
    s = bootstrap(tmp_path)
    try:
        s.source_evidence = SourceEvidenceService(s.db, tmp_path/'evidence', current_binding=lambda _: binding())
        record = s.source_evidence.create('run', binding(), new_flashcut_policy())
        calls = []
        def runner(argv, **kwargs):
            request = json.loads(Path(argv[-1]).read_text())
            assert request['version'] == 'flashcut_helper.v1'
            assert request['evidence_id'] == record['id']
            calls.append(request)
            return subprocess.CompletedProcess(argv, 3, '{"status":"failed","error":"resource_limit_exhausted"}', '')
        s.commands.enqueue('source_evidence', {'evidence_id': record['id']}, phase='analyze_dense')
        job = s.scheduler.claim()
        for index in range(3):
            work = SourceEvidenceWork(s, Path(__file__).resolve().parents[1], runner=runner,
                                      free_bytes=lambda _: 100*1024**3, owned_alive=lambda _: False)
            if index < 2:
                assert work.execute({'evidence_id': record['id']}, job)['status'] == 'pending'
            else:
                with pytest.raises(ContractError, match='resource_limit_exhausted'):
                    work.execute({'evidence_id': record['id']}, job)
        with pytest.raises(ContractError, match='source_evidence_repair_exhausted'):
            work.execute({'evidence_id':record['id']}, job)
        assert len(calls) == 3
        assert s.db.conn.execute('SELECT 1 FROM meta WHERE key=?', ('local_work:'+job['id'],)).fetchone() is None
    finally:
        s.db.close()


def test_source_evidence_backup_restores_hash_bound_bundle(tmp_path):
    from modules.factory.operations.backup_restore import create_backup, restore_into
    from modules.factory.store import Database
    s = bootstrap(tmp_path/'source')
    restored = None
    try:
        evidence = s.source_evidence
        record = evidence.create('run-test', binding(), new_flashcut_policy())
        blob = evidence.blobs.put({'test_evidence': [1,2,3]})
        manifest = create_backup(s.db,tmp_path/'source',tmp_path/'backup')
        assert any(p.startswith('recovery/source_evidence/blobs/') for p in manifest['files'])
        result = restore_into(tmp_path/'backup',tmp_path/'restored')
        restored = Database(result['database'])
        service = SourceEvidenceService(restored,Path(result['database']).parent/'source_evidence')
        assert service.get(record['id'])['binding'] == binding()
        assert service.blobs.read(blob) == {'test_evidence':[1,2,3]}
    finally:
        if restored:
            restored.close()
        s.db.close()
