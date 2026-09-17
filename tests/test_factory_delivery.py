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
            return R("abc\tmy file.mp4\tvideo/mp4\ndef\tother\tvideo/mp4\n")
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
