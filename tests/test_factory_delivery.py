from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
"""F25 — verified Drive delivery.

Intent persisted before transfer; remote verification (parent, name,
size, MD5) is the only completion; lost acks reconcile by content;
failures retain the local final and retry transfer only.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.factory.delivery import DeliveryService, delivery_name
from modules.factory.domain.errors import ContractError
from modules.factory.delivery.service import _md5
from modules.factory.integrations.drive import GdriveCLI
from modules.factory.store import Database
from modules.factory.testing.fakes import FakeDrive

FOLDER = "folder-authorized"


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    drive = FakeDrive(tmp_path / "remote.json")
    svc = DeliveryService(db, drive, effects=FixtureEffects(db, Executor(db)))
    final = tmp_path / "exp1-A-hook-r1-30s.mp4"
    final.write_bytes(b"final-bytes" * 1000)
    return db, drive, svc, final, tmp_path


def test_naming_is_descriptive():
    assert delivery_name("exp1", "A", "hook", 2, 30.0) == \
        "exp1-A-hook-r2-30s.mp4"
    assert delivery_name("seed42", "B", "hook+body", 1, 12.5) == \
        "seed42-B-hook+body-r1-12.5s.mp4"


def test_saved_delivery_account_cannot_change_during_recovery(env):
    _, drive, svc, final, _ = env
    drive.expected_account = 'first@example.test'
    assert svc.deliver('account-bound', final, final.name, FOLDER)['status'] == 'verified'
    drive.expected_account = 'second@example.test'
    with pytest.raises(ContractError, match='delivery_account_changed'):
        svc.reconcile('account-bound')
    assert drive.doc['uploads'] == 1


def test_external_receipt_never_uploads_and_keeps_explicit_remote_identity(env):
    db, drive, svc, final, _ = env
    fid = drive.plant(FOLDER, 'external-final.mp4', final.read_bytes())
    # plant returns an ID in the fixture; the production method only reads.
    result = svc.reconcile_external('external', final, 'external-final.mp4', FOLDER, fid,
        variant_plan_id='v1', experiment_revision=1)
    assert result['status'] == 'verified'
    assert drive.doc['uploads'] == 0
    assert svc.reconcile_external('external', final, 'external-final.mp4', FOLDER, fid,
        variant_plan_id='v1', experiment_revision=1)['status'] == 'verified'
    assert drive.doc['uploads'] == 0
    receipt = json.loads(db.uow().records.get('delivery', 'external')['body'])
    assert receipt['provenance'] == 'external_verified'
    assert db.uow().records.get('delivery', 'external')['status'] == 'verified'
    with pytest.raises(ContractError, match='external_verification_only'):
        svc.retry('external', final)
    assert drive.doc['uploads'] == 0


@pytest.mark.parametrize('problem', ['duplicate', 'checksum', 'identity', 'size'])
def test_external_receipt_rejects_uncertain_remote_matches(env, problem):
    _, drive, svc, final, _ = env
    fid = drive.plant(FOLDER, 'external.mp4', final.read_bytes())
    if problem == 'duplicate': drive.plant(FOLDER, 'external.mp4', final.read_bytes())
    if problem == 'checksum': drive.set_no_md5()
    if problem == 'identity': fid = 'unrelated-file'
    if problem == 'size':
        original = drive.stat
        drive.stat = lambda fid: {**original(fid), 'size':2}
    result = svc.reconcile_external('external', final, 'external.mp4', FOLDER, fid,
        variant_plan_id='v1', experiment_revision=1)
    assert result['status'] != 'verified'
    assert drive.doc['uploads'] == 0


def test_duplicate_remote_matches_are_ambiguous_and_never_upload(env):
    _, drive, svc, final, _ = env
    drive.plant(FOLDER, final.name, final.read_bytes())
    drive.plant(FOLDER, final.name, final.read_bytes())
    with pytest.raises(ContractError, match='ambiguous_remote_match'):
        svc.deliver('ambiguous', str(final), final.name, FOLDER)
    assert drive.doc['uploads'] == 0


def test_verified_upload_receipt(env):
    db, drive, svc, final, _ = env
    r = svc.deliver("dlv-1", str(final), final.name, FOLDER)
    assert r["status"] == "verified" and r["file_id"]
    body = json.loads(db.uow().records.get("delivery", "dlv-1")["body"])
    assert body["status"] == "verified"
    assert body["remote_md5"] == _md5(final)
    assert body["file_sha256"]
    assert body["drive_file_id"] == r["file_id"]
    assert body["drive_link"].endswith(r["file_id"] + "/view")
    assert body["verified_at"] and body["parent_folder_id"] == FOLDER
    ev = db.uow().events.since("delivery:dlv-1")
    assert any(e["type"] == "upload_verified" for e in ev)


def test_delivery_intent_is_atomic_before_remote_access(env):
    import sqlite3
    db, drive, svc, final, _ = env
    db.conn.execute("""CREATE TEMP TRIGGER fail_delivery_metadata BEFORE UPDATE ON records
        WHEN NEW.kind='delivery' BEGIN SELECT RAISE(ABORT,'simulated crash'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        svc.deliver('atomic', final, final.name, FOLDER)
    assert drive.doc['uploads'] == 0
    db.conn.execute('DROP TRIGGER fail_delivery_metadata')
    assert svc.deliver('atomic', final, final.name, FOLDER)['status'] == 'verified'
    assert drive.doc['uploads'] == 1


def test_intent_persisted_before_transfer(env):
    db, drive, svc, final, _ = env
    drive.set_auth(False)
    with pytest.raises(Exception):
        svc.deliver("dlv-2", str(final), final.name, FOLDER)
    body = json.loads(db.uow().records.get("delivery", "dlv-2")["body"])
    assert body["status"] == "failed"          # intent existed
    assert body["file_sha256"]                # bound to exact bytes


def test_lost_ack_reconciles_by_content(env):
    db, drive, svc, final, _ = env
    drive.lose_next_upload()
    r = svc.deliver("dlv-3", str(final), final.name, FOLDER)
    assert r["status"] == "verified"
    assert drive.doc["uploads"] == 1           # one remote file, no dup
    body = json.loads(db.uow().records.get("delivery", "dlv-3")["body"])
    assert body["status"] == "verified"


def test_external_match_with_missing_checksum_never_triggers_duplicate_upload(env):
    db, drive, svc, final, _ = env
    uploaded = drive.upload(FOLDER, str(final), final.name)
    original = drive.stat
    def incomplete(fid):
        value = original(fid)
        return {k: v for k, v in value.items() if k != 'md5'}
    drive.stat = incomplete
    listing = drive.list_files
    drive.list_files = lambda parent: [{k: v for k, v in row.items() if k != 'md5'} for row in listing(parent)]
    count = drive.doc['uploads']
    result = svc.deliver('external-uncertain', str(final), final.name, FOLDER)
    assert result['status'] != 'verified'
    assert drive.doc['uploads'] == count


def test_restart_reconcile_recovers(env):
    db, drive, svc, final, tmp = env
    drive.lose_next_upload()
    svc.deliver("dlv-4", str(final), final.name, FOLDER)
    # "restart": new service over the same persisted remote state
    svc2 = DeliveryService(db, FakeDrive(tmp / "remote.json"))
    # second delivery of same name+content reuses, doesn't duplicate
    r = svc2.deliver("dlv-5", str(final), final.name, FOLDER)
    assert r["status"] == "verified" and r["reused"]
    assert drive.doc["uploads"] == 1


def test_same_name_different_content_is_conflict(env):
    db, drive, svc, final, _ = env
    drive.plant(FOLDER, final.name, b"different content")
    r = svc.deliver("dlv-6", str(final), final.name, FOLDER)
    assert r["status"] == "conflict"
    assert "not proof" in r["detail"]
    assert drive.doc["uploads"] == 0           # never overwrote


def test_missing_checksum_is_unverified(env):
    db, drive, svc, final, _ = env
    drive.set_no_md5()
    r = svc.deliver("dlv-7", str(final), final.name, FOLDER)
    assert r["status"] == "unverified"
    assert "checksum_unavailable" in r["problems"]
    body = json.loads(db.uow().records.get("delivery", "dlv-7")["body"])
    assert body["status"] != "verified"        # not "complete"


def test_retry_is_transfer_only(env):
    db, drive, svc, final, _ = env
    drive.set_auth(False)
    with pytest.raises(Exception):
        svc.deliver("dlv-8", str(final), final.name, FOLDER)
    drive.set_auth(True)
    r = svc.retry("dlv-8", str(final))
    assert r["status"] == "verified"
    # retry with a DIFFERENT file is a contract violation, not an upload
    changed = final.with_name("changed.mp4")
    changed.write_bytes(b"changed")
    with pytest.raises(ContractError, match="final_changed"):
        svc.retry("dlv-8", str(changed))


def test_failure_retains_local_final(env):
    db, drive, svc, final, _ = env
    drive.set_auth(False)
    with pytest.raises(Exception):
        svc.deliver("dlv-9", str(final), final.name, FOLDER)
    assert final.exists()                      # local final kept


def test_cli_parses_listing(tmp_path):
    class R:
        def __init__(s, out="", rc=0):
            s.stdout, s.returncode, s.stderr = out, rc, ""
    seen = []
    def runner(argv, timeout=300):
        seen.append(argv)
        if "list" in argv:
            separator = argv[argv.index('--field-separator') + 1]
            if separator == '\t':
                # gdrive 3.9.1 uses aligned table output for a tab separator.
                return R("abc   my file.mp4   regular   100 B   2026-09-21 00:00:00\n")
            return R(separator.join(['abc', 'my file.mp4', 'regular', '100 B', '2026-09-21 00:00:00'])+'\n')
        if "upload" in argv:
            return R("drv-new-id\n")
        return R("Name: x.mp4\nMD5: deadbeef\nSize: 100\n"
                 "Parents: folder-authorized\n")
    cli = GdriveCLI(runner=runner)
    assert cli.list_files(FOLDER)[0] == {"id": "abc", "name": "my file.mp4"}
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local bytes")
    assert cli.upload(FOLDER, source, "descriptive.mp4")["id"] == "drv-new-id"
    assert Path(seen[-1][-1]).name == "descriptive.mp4"
    st = cli.stat("abc")
    assert st["md5"] == "deadbeef" and st["size"] == 100
