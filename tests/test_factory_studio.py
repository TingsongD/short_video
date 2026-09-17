"""F29 — owned Studio sessions and revision-bound feedback."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.factory.domain.errors import ContractError
from modules.factory.resources import ResourceRegistry
from modules.factory.store import Database
from modules.factory.studio import StudioService


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    reg = ResourceRegistry(db)
    launcher = lambda ws: {"pid": 4242, "birth": "b4242",
                           "command": "hypit studio", "port": 5100}
    return db, reg, StudioService(db, registry=reg, launcher=launcher)


def test_session_registers_owned_resource(env):
    db, reg, svc = env
    r = svc.open_session("s1", "/tmp/comp", "expA")
    assert r["state"] == "open" and r["port"] == 5100
    res = reg.get("studio-s1")
    assert res["pid"] == 4242 and res["cls"] == "per_job"
    assert res["ports"] == [5100]


def test_close_marks_resource_stopped(env):
    db, reg, svc = env
    svc.open_session("s1", "/tmp/comp", "expA")
    svc.close_session("s1")
    assert reg.get("studio-s1")["status"] == "stopped"
    body = svc._get("studio_session:s1")
    assert body["state"] == "closed" and body["closed_at"]


def test_comment_becomes_proposed_change(env):
    db, _, svc = env
    svc.open_session("s1", "/tmp/comp", "expA")
    r = svc.import_comment("c1", "expA-C", 12.5, "hook feels slow",
                           source_revision=2, session_id="s1")
    assert r["status"] == "proposed" and r["bound_revision"] == 2
    body = svc._get("proposed_change:c1")
    assert body["at_s"] == 12.5 and body["variant_id"] == "expA-C"
    assert body["diff"]["instruction"] == "hook feels slow"
    assert body["estimated_cost"] == "requires_quote"   # not free regen


def test_comment_requires_exact_revision(env):
    _, _, svc = env
    with pytest.raises(ContractError, match="missing_revision"):
        svc.import_comment("c2", "expA-C", 1.0, "x", None)


def test_comment_on_closed_session_rejected(env):
    _, _, svc = env
    svc.open_session("s1", "/tmp/comp", "expA")
    svc.close_session("s1")
    with pytest.raises(ContractError, match="session_closed"):
        svc.import_comment("c3", "expA-C", 1.0, "x", 0, session_id="s1")


def test_mark_stale_blocks_silent_reuse(env):
    _, _, svc = env
    svc.import_comment("c4", "expA-C", 1.0, "x", source_revision=1)
    r = svc.mark_stale("c4", new_revision=2)
    assert r["status"] == "stale" and r["invalidated_by"] == 2


def test_proposed_changes_scoped_to_variant(env):
    _, _, svc = env
    svc.import_comment("c5", "expA-C", 1.0, "x", 0)
    svc.import_comment("c6", "expA-B", 2.0, "y", 0)
    got = svc.proposed_changes("expA-C")
    assert len(got) == 1 and got[0]["id"] == "c5"


def test_missing_studio_launcher_blocks(env):
    db,reg,_=env
    with pytest.raises(ContractError,match='studio_unavailable'):
        StudioService(db,registry=reg).open_session('absent','/tmp/comp','video')


def test_closed_session_can_open_a_new_revision(tmp_path):
    from modules.factory.store import Database
    from modules.factory.studio.service import StudioService
    db=Database(tmp_path/'studio.db')
    s=StudioService(db,launcher=lambda ws:{'pid':0,'birth':'fixture','command':'fixture','port':None})
    s.open_session('reopen','/fixture','variant-a')
    s._set('studio_session:reopen',state='closed')
    s.open_session('reopen','/fixture','variant-a')
    assert len(db.uow().records.revisions('studio_session','reopen'))==2
    assert s._get('studio_session:reopen')['state']=='open'
