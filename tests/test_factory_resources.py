"""F26 — process ownership and resource cleanup.

Owned resources carry identity evidence (pid+birth+command); cleanup
stops only owned idle processes, retains shared/application services,
and reports — never kills — unrelated listeners.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.factory.resources import CleanupService, ResourceRegistry
from modules.factory.store import Database


class FakeOS:
    """Simulated kernel view: process table, listeners, kills."""

    def __init__(self):
        self.table = {}
        self.listeners = {}
        self.killed = []
        self.stubborn = set()

    def table_fn(self):
        return dict(self.table)

    def kill_fn(self, pid, sig):
        self.killed.append((pid, sig))
        if pid in self.stubborn:
            return
        self.table.pop(pid, None)
        self.listeners = {p: q for p, q in self.listeners.items()
                          if q != pid}

    def port_fn(self):
        return dict(self.listeners)

    def spawn(self, pid, command, birth=None, ppid=1):
        self.table[pid] = {"pid": pid, "ppid": ppid,
                           "birth": birth or f"birth{pid}",
                           "command": command}


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    reg = ResourceRegistry(db)
    os_ = FakeOS()
    svc = CleanupService(reg, table_fn=os_.table_fn,
                         kill_fn=os_.kill_fn, port_fn=os_.port_fn,
                         sleep_fn=lambda s: None)
    return db, reg, os_, svc


def _own(reg, rid, pid, os_, owner, cls="per_job", holders=(),
         ports=(), command="ffmpeg -i x"):
    os_.spawn(pid, command)
    reg.register(rid, pid, os_.table[pid]["birth"], command, owner,
                 cls=cls, holders=holders, ports=ports)


def test_listener_inspection_failure_does_not_claim_free_ports(monkeypatch):
    from types import SimpleNamespace
    from modules.factory.resources.service import scan_listeners
    from modules.factory.domain.errors import ContractError
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(returncode=2, stdout='', stderr='denied'))
    with pytest.raises(ContractError, match='listener_inspection_unavailable'):
        scan_listeners()


def test_cleanup_preserves_stop_evidence_when_final_inspection_fails(env):
    from modules.factory.domain.errors import ContractError
    _, reg, os_, svc = env
    _own(reg, 'render', 100, os_, 'future', ports=(8105,))
    scans = iter([{8105: 100}, None])
    def scan():
        result = next(scans)
        if result is None:
            raise ContractError('listener_inspection_unavailable')
        return result
    svc.ports = scan
    result = svc.cleanup('future')
    assert result['state'] == 'blocked'
    assert result['stopped'] == [{'id':'render','pid':100}]
    assert result['ports_verified'] is False


def test_per_job_cleanup_kills_and_frees_port(env):
    _, reg, os_, svc = env
    _own(reg, "r-render-a", 100, os_, "expA", ports=(8123,))
    os_.listeners[8123] = 100
    r = svc.cleanup("expA")
    assert r["state"] == "verified"
    assert r["stopped"] == [{"id": "r-render-a", "pid": 100}]
    assert 100 not in os_.table and 8123 not in os_.listeners
    assert (100, 15) in os_.killed            # graceful TERM first


def test_shared_runtime_retained_for_other_holder(env):
    _, reg, os_, svc = env
    _own(reg, "r-a", 100, os_, "expA")
    _own(reg, "r-shared", 200, os_, "expA", cls="shared",
         holders=("expA", "expB"), command="hypit serve")
    r = svc.cleanup("expA")
    assert any(x["id"] == "r-shared" and x["why"] == "shared_active"
               for x in r["retained"])
    assert 200 in os_.table                  # B still runs
    assert reg.get("r-shared")["holders"] == ["expB"]


def test_application_service_never_stopped(env):
    _, reg, os_, svc = env
    _own(reg, "r-dash", 300, os_, "expA", cls="application",
         command="uvicorn app")
    r = svc.cleanup("expA")
    assert 300 in os_.table
    assert r["retained"][0]["why"] == "application"
    assert (300, 15) not in os_.killed


def test_pid_reuse_not_killed(env):
    _, reg, os_, svc = env
    os_.spawn(100, "ffmpeg -i x", birth="old-birth")
    reg.register("r-old", 100, "old-birth", "ffmpeg -i x", "expA")
    os_.table.pop(100)
    os_.spawn(100, "someone-elses-daemon", birth="new-birth")
    r = svc.cleanup("expA")
    assert 100 in os_.table                  # stranger untouched
    assert not any(pid == 100 for pid, _ in os_.killed)
    assert r["pid_reuse_untouched"][0]["why"] == "pid_reused"
    assert reg.get("r-old")["status"] == "reaped"


def test_stubborn_process_blocks(env):
    _, reg, os_, svc = env
    _own(reg, "r-stub", 100, os_, "expA")
    os_.stubborn.add(100)
    r = svc.cleanup("expA")
    assert r["state"] == "blocked" and r["survivors"] == [100]
    sigs = [s for p, s in os_.killed if p == 100]
    assert sigs == [15, 15, 9] or set(sigs) == {15, 9}  # TERM then KILL


def test_unrelated_port_listener_reported(env):
    _, reg, os_, svc = env
    _own(reg, "r-prev", 100, os_, "expA", ports=(8123,))
    os_.spawn(999, "nginx")
    os_.listeners[8123] = 999                # unrelated listener
    os_.table.pop(100)                       # our proc already dead
    r = svc.cleanup("expA")
    assert r["port_conflicts"] == [8123]
    assert r["state"] == "blocked"
    assert not any(pid == 999 for pid, _ in os_.killed)


def test_reap_stale_after_crash(env):
    _, reg, os_, svc = env
    _own(reg, "r-live", 100, os_, "expA")
    reg.register("r-reused", 200, "b-old", "ffmpeg", "expA")
    os_.spawn(200, "foreign-app", birth="b-new")
    r = svc.reap_stale("expA")
    assert r["reaped"] == ["r-live"]
    assert r["foreign_untouched"] == [
        {"pid": 200, "command": "foreign-app"}]
    assert 200 in os_.table


def test_completion_requires_qc_delivery_cleanup(env):
    _, reg, os_, svc = env
    _own(reg, "r-x", 100, os_, "expA")
    c = svc.complete("expA", qc_passed=True, delivery_status="verified")
    assert c["complete"] is True
    _, reg2, os2, svc2 = env
    c2 = svc2.complete("expB", qc_passed=True,
                       delivery_status="failed")
    assert c2["complete"] is False
    assert "delivery_failed" in c2["problems"]
    assert c2["cleanup"] == "verified"        # cleanup still ran


def test_delivery_failure_cleanup_keeps_state(env):
    db, reg, os_, svc = env
    _own(reg, "r-render", 100, os_, "expA")
    r = svc.cleanup("expA")                   # upload failed → clean idle
    assert r["state"] == "verified"
    assert reg.get("r-render")["status"] == "stopped"


def test_receipt_event_persisted(env):
    db, reg, os_, svc = env
    _own(reg, "r-y", 100, os_, "expA")
    svc.cleanup("expA")
    ev = db.uow().events.since("resources:expA")
    assert ev and ev[-1]["type"] == "cleanup_receipt"
    import json
    body = json.loads(ev[-1]["body"])
    assert body["stopped"] and body["at"]


def test_inspect_reports_live_vs_stale(env):
    _, reg, os_, svc = env
    _own(reg, "r-live", 100, os_, "expA", ports=(8000,))
    reg.register("r-dead", 200, "b200", "gone", "expA")
    os_.listeners[8000] = 100
    v = svc.inspect()
    assert v["live"] == ["r-live"]
    assert "r-dead" in v["stale"]
    assert v["ports_listening"] == [8000]


def test_cleanup_owns_descendants_before_parent_exits(env):
    _,reg,os_,svc=env
    _own(reg,'parent',100,os_,'video',ports=(8123,))
    os_.spawn(101,'render child',ppid=100); os_.listeners[8123]=101
    out=svc.cleanup('video')
    assert out['state']=='verified'
    assert 100 not in os_.table and 101 not in os_.table
    assert any(x['pid']==101 for x in out['stopped'])


def test_failed_cleanup_preserves_child_identity_for_retry(env):
    _,reg,os_,svc=env
    _own(reg,'parent',100,os_,'video')
    os_.spawn(101,'stubborn child',ppid=100);os_.stubborn.add(101)
    out=svc.cleanup('video')
    assert out['state']=='blocked' and 101 in out['survivors']
    os_.table[101]['ppid']=1;os_.stubborn.clear()
    assert svc.cleanup('video')['state']=='verified'
    assert 101 not in os_.table


def test_last_holder_cleanup_does_not_lose_resource(env):
    _,reg,os_,svc=env
    _own(reg,'shared',100,os_,'video-a',cls='shared',holders=('video-b',))
    reg.release_holder('shared','video-b')
    assert svc.cleanup('video-b')['state']=='verified'
    assert 100 not in os_.table
