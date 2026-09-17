"""F30 — operations: config precedence, owned services, port
conflicts, dispatch gates, backup/restore integrity and isolation.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.factory.cli import main as cli
from modules.factory.domain.errors import ContractError
from modules.factory.operations import (ServiceManager,
                                        activation_gate, create_backup,
                                        dispatch_gate, doctor,
                                        load_config, restore_into)
from modules.factory.resources import ResourceRegistry
from modules.factory.store import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


# ------------------------------------------------------------ config

def test_config_precedence_nonempty_env(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "secrets.toml").write_text(
        'API_PORT = "8100"\nSECRET_X = "from-toml"\n')
    (tmp_path / ".env").write_text(
        "API_PORT=8200\nSECRET_X=from-env-file\n")
    cfg = load_config(tmp_path, env={"API_PORT": "8300",
                                     "EMPTY": ""})
    assert cfg["values"]["API_PORT"] == "8300"          # env wins
    assert cfg["credential_refs_present"]["CANVAS_TOKEN"] == "absent"


def test_config_env_beats_dotenv_beats_toml(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "secrets.toml").write_text('API_PORT = "1"\n')
    (tmp_path / ".env").write_text("API_PORT=2\n")
    assert load_config(tmp_path, env={})["values"]["API_PORT"] == "2"
    assert load_config(tmp_path,
                       env={"API_PORT": "3"}
                       )["values"]["API_PORT"] == "3"


def test_config_never_exposes_credentials_as_safe(tmp_path):
    cfg = load_config(tmp_path, env={"CANVAS_TOKEN": "sekrit"})
    assert "CANVAS_TOKEN" not in cfg["values"]
    assert cfg["credential_refs_present"]["CANVAS_TOKEN"] == "set"


# ---------------------------------------------------------- services

class FakeSpawn:
    def __init__(self, pid=777):
        self.pid = pid
        self.argv = None

    def __call__(self, argv, workspace):
        self.argv = argv
        return {"pid": self.pid}


def _mgr(db, listeners, spawn=None):
    reg = ResourceRegistry(db)
    spawn = spawn or FakeSpawn()
    return reg, ServiceManager(reg, spawn_fn=spawn,
                               port_fn=lambda: listeners,health_fn=lambda *a:True,
                               table_fn=lambda:{spawn.pid:{'pid':spawn.pid,'ppid':1,'birth':'fixture','command':'fixture service'}}), spawn


def test_port_conflict_fails_clearly(db):
    reg, mgr, _ = _mgr(db, {8100: 999})
    with pytest.raises(ContractError, match="port_occupied"):
        mgr.start("api", ["serve", "--port", "{port}"], "/w", 8100)
    assert reg.get("service-api") is None            # nothing started


def test_port_alternative_selected(db):
    reg, mgr, spawn = _mgr(db, {8100: 999})
    out = mgr.start("api", ["serve", "--port", "{port}"], "/w", 8100,
                    alternatives=(8101,))
    assert out["port"] == 8101
    assert spawn.argv == ["serve", "--port", "8101"]
    assert reg.get("service-api")["ports"] == [8101]


def test_own_port_is_idempotent(db):
    reg, mgr, _ = _mgr(db, {})
    out1 = mgr.start("api", ["serve"], "/w", 8100)
    rec = reg.get("service-api")
    # a later start sees the same live process → already_running
    table = {rec["pid"]: {"pid": rec["pid"], "ppid": 1,
                         "birth": rec["birth"],
                         "command": rec["command"]}}
    _, mgr2, _ = _mgr(db, {8100: rec["pid"]})
    mgr2.table = lambda: table
    out = mgr2.start("api", ["serve"], "/w", 8100)
    assert out["state"] == "already_running"
    assert out["port"] == 8100


def test_service_health_absent_and_running(db):
    _, mgr, _ = _mgr(db, {})
    assert mgr.health("api")["state"] == "absent"


def test_stop_only_marks_owned_service(db):
    reg, mgr, _ = _mgr(db, {})
    killed = []
    mgr.stop("api", kill_fn=lambda p, s: killed.append((p, s)))
    assert killed == []                              # absent → no kill


# ------------------------------------------------------------- gates

def test_dispatch_gate_clean(db):
    assert dispatch_gate(db)["allowed"] is True


def test_dispatch_gate_blocks_unfinished(db):
    db.uow().conn.execute(
        "INSERT INTO jobs(id,logical_key,phase,status,created_at,"
        "updated_at) VALUES('j1','k1','dispatch','leased','now','now')")
    db.uow().conn.execute(
        "INSERT INTO attempts(id,job_id,attempt_seq,status,body,"
        "created_at,updated_at)"
        " VALUES('a1','j1',0,'running','{}','now','now')")
    gate = dispatch_gate(db)
    assert gate["allowed"] is False
    assert gate["unresolved"][0]["attempt"] == "a1"


def test_activation_gate_after_restore(db):
    assert activation_gate(db)["dispatch_enabled"] is True
    db.uow().conn.execute(
        "INSERT INTO jobs(id,logical_key,phase,status,created_at,"
        "updated_at) VALUES('j1','k1','dispatch','leased','now','now')")
    db.uow().conn.execute(
        "INSERT INTO attempts(id,job_id,attempt_seq,status,body,"
        "created_at,updated_at)"
        " VALUES('a2','j1',0,'accepted','{}','now','now')")
    gate = activation_gate(db)
    assert gate["dispatch_enabled"] is False
    assert gate["action"] == "run reconcile against provider remote state"


# ------------------------------------------------------ backup/restore

def test_backup_manifest_and_verify(db, tmp_path):
    from modules.factory.artifacts.registry import ArtifactStore
    from modules.factory.audio import pcm
    source = tmp_path / "source.wav"
    source.write_bytes(pcm.write_wav(pcm.sine(0.1)))
    artifact = ArtifactStore(tmp_path / "assets", db).intake_file(
        source, provenance="manual", source_key="backup-fixture")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"charge": 5}\n')
    m = create_backup(db, tmp_path, tmp_path / "bk",
                      ledger_paths=[ledger])
    assert m["db_integrity"]["integrity"] == "ok"
    assert "factory.db" in m["files"]
    assert "ledger.jsonl" in m["files"]          # ignored ledger backed up
    fin = json.loads((tmp_path / "bk" / "financial-state.json")
                     .read_text())
    assert "unresolved_intents" in fin and "budgets" in fin
    restored = tmp_path / "restored-with-assets"
    restore_into(tmp_path / "bk", restored)
    target_db = Database(restored / "data/factory/factory.db")
    target_store = ArtifactStore(restored / "data/factory/artifacts", target_db)
    assert target_store.path_for(artifact.id).read_bytes() == source.read_bytes()
    assert (restored / "data/costs/ledger.jsonl").read_bytes() == ledger.read_bytes()


def test_restore_into_fresh_root_verifies(db, tmp_path):
    create_backup(db, tmp_path, tmp_path / "bk")
    out = restore_into(tmp_path / "bk", tmp_path / "restored")
    assert out["integrity"]["integrity"] == "ok"
    assert out["dispatch"].startswith("gated")
    assert (tmp_path / "restored" / "data" / "factory" / "factory.db").exists()
    # original untouched
    assert (tmp_path / "bk" / "factory.db").exists()


def test_restore_refuses_existing_root(db, tmp_path):
    create_backup(db, tmp_path, tmp_path / "bk")
    (tmp_path / "occupied").mkdir()
    (tmp_path / "occupied" / "x").write_text("keep")
    with pytest.raises(ContractError, match="restore_target_exists"):
        restore_into(tmp_path / "bk", tmp_path / "occupied")


def test_restore_detects_tampered_file(db, tmp_path):
    create_backup(db, tmp_path, tmp_path / "bk")
    (tmp_path / "bk" / "artifacts-manifest.json").write_text("tampered")
    with pytest.raises(ContractError, match="restore_corrupt"):
        restore_into(tmp_path / "bk", tmp_path / "fresh")


# ---------------------------------------------------------------- cli

def test_cli_doctor_and_config(tmp_path, capsys):
    (tmp_path / "config").mkdir()
    assert cli(["--root", str(tmp_path), "config"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "values" in out and "credential_refs_present" in out


def test_cli_gate_exit_codes(tmp_path, capsys):
    assert cli(["--root", str(tmp_path), "gate"]) == 0
    db = Database(tmp_path / "data" / "factory" / "factory.db")
    db.uow().conn.execute(
        "INSERT INTO jobs(id,logical_key,phase,status,created_at,"
        "updated_at) VALUES('j','k','dispatch','leased','now','now')")
    db.uow().conn.execute(
        "INSERT INTO attempts(id,job_id,attempt_seq,status,body,"
        "created_at,updated_at)"
        " VALUES('a9','j',0,'running','{}','now','now')")
    assert cli(["--root", str(tmp_path), "gate"]) == 1


def test_doctor_real_tools(tmp_path):
    out = doctor(tmp_path)
    names = {c["name"] for c in out["checks"]}
    assert {"python", "ffmpeg", "node", "hypit", "gdrive", "disk"} \
        <= names
    assert all(c["ok"] for c in out["checks"]
               if c["name"] in ("python", "ffmpeg", "disk"))
