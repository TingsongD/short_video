"""Repository-owned offline helper; launched only with a persisted job lease."""
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import threading
import time

from ..domain.errors import ContractError
from ..store import Database
from ..store.uow import utcnow
from .source_evidence import SourceEvidenceService, binding_from_db
from .evidence_policy import validate_flashcut_policy


def storage_problem(volume, roots, limits):
    """Fail closed if the evidence/media storage safety check is unavailable.

    The cap conservatively includes the registered-media root as well as the
    dedicated arrays store; selected images/windows must not evade admission.
    No file is removed to make space.
    """
    try:
        if shutil.disk_usage(volume).free < limits['min_free_bytes']:
            return 'source_evidence_disk_full'
        total=0
        def failed(error):raise error
        for root in dict.fromkeys(Path(p).resolve() for p in roots):
            if not root.is_dir():return 'source_evidence_storage_unavailable'
            for parent,_,files in os.walk(root,onerror=failed,followlinks=False):
                for name in files:
                    total+=(Path(parent)/name).stat().st_size
                    if total>limits['max_disk_bytes']:return 'source_evidence_disk_limit'
    except OSError:
        return 'source_evidence_storage_unavailable'
    return None


def execute(request):
    expected = {'version', 'database', 'evidence_id', 'job_id', 'fencing_token', 'lease_owner'}
    if (not isinstance(request, dict) or set(request) != expected
            or request['version'] != 'flashcut_helper.v1'
            or type(request['fencing_token']) is not int or request['fencing_token'] < 1
            or any(not isinstance(request[k], str) or not request[k] for k in expected - {'fencing_token'})):
        raise ContractError('invalid_helper_request', 'request')
    database = Path(request['database']).resolve()
    if not database.is_file():
        raise ContractError('invalid_helper_request', 'database')
    db = Database(database)
    stop = threading.Event()
    alive = [time.monotonic()]
    try:
        def verify(u, job_id, fencing):
            row = u.jobs.get(job_id)
            if (not row or row['fencing_token'] != fencing or row['lease_owner'] != request['lease_owner']
                    or row['status'] not in ('reserved', 'running') or not row['lease_expires']
                    or row['lease_expires'] <= utcnow()):
                raise ContractError('stale_fencing', 'source_evidence')
        service = SourceEvidenceService(db, database.parent/'source_evidence', verify_lease=verify,
                                        current_binding=lambda rid: binding_from_db(db, rid))
        record = service.get(request['evidence_id'])
        policy = validate_flashcut_policy(record['policy'])
        lease = {k: request[k] for k in ('job_id', 'fencing_token')}
        with db.uow() as u:
            service._guard(u, record, None, lease)
        source = db.uow().artifacts.get(record['binding']['source_artifact_id'])
        row = db.conn.execute("SELECT value FROM meta WHERE key='artifact_root'").fetchone()
        root = Path(row[0]).resolve() if row else database.parent/'artifacts'
        path = (root/source['local_path']).resolve()
        if not path.is_relative_to(root):
            raise ContractError('evidence_path_escape', 'source')
        problem=storage_problem(database.parent,[service.blobs.root,root],policy['resources'])
        if problem:raise ContractError(problem,'source_evidence')
        def watchdog():
            checks = 0
            while not stop.wait(1):
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if sys.platform != 'darwin':
                    rss *= 1024
                error = ('resource_limit_exhausted' if rss > policy['resources']['rss_bytes'] else
                         'source_evidence_no_progress' if time.monotonic()-alive[0] > policy['resources']['no_progress_seconds'] else None)
                checks += 1
                if checks % 10 == 0:
                    error = storage_problem(database.parent,[service.blobs.root,root],policy['resources']) or error
                if error:
                    print(json.dumps({'status': 'failed', 'error': error}), flush=True)
                    os._exit(3)  # This process owns no child services or ports.
        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        def progress(**values):
            alive[0] = time.monotonic()
            service.report_progress(record['id'], values, lease=lease)
        from .frame_encoder import PEEncoder
        from .dense_source import analyze_source
        repo = Path(__file__).resolve().parents[3]
        from .helper_readiness import verify_installation
        verify_installation(repo)
        encoder = PEEncoder(repo/'vendor/flashcut-perception-models', repo/'vendor/flashcut-helper/models/PE-Core-S16-384.pt')
        result = analyze_source(service, record['id'], path, encoder,
                                binding=record['binding'], lease=lease, progress=progress)
        return {'status': 'complete', 'evidence_id': record['id'], 'manifest': result['manifest']}
    finally:
        stop.set()
        db.close()


def main():
    try:
        if len(sys.argv) != 2:
            raise ContractError('invalid_helper_request', 'arguments')
        request_file = Path(sys.argv[1])
        if request_file.stat().st_size > 65536:
            raise ContractError('invalid_helper_request', 'size')
        result = execute(json.loads(request_file.read_text()))
    except ContractError as error:
        print(json.dumps({'status': 'failed', 'error': error.code, 'field': error.field}), flush=True)
        return 2
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': 'helper_failed', 'error_type': type(error).__name__}), flush=True)
        return 2
    print(json.dumps(result), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
