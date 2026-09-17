"""F06 — scheduler: DAG validation, capacity, leases, fencing, pause,
reclaim. All offline."""
import pytest

from modules.factory.domain import Job
from modules.factory.scheduler import (DagError, FencingError,
                                       ResourcePolicy, Scheduler,
                                       validate_dag)
from modules.factory.store import Database

NOW = "2026-09-16T12:00:00Z"


@pytest.fixture
def sched(tmp_path):
    db = Database(tmp_path / "f.db")
    yield Scheduler(db, worker_id="w1", lease_s=120)
    db.close()


def _job(jid, phase="generate_jimeng", deps=()):
    return Job(schema_version="job.v1", id=jid,
               created_at=NOW, logical_key=f"lk-{jid}", phase=phase,
               depends_on=list(deps), status="waiting_dependencies")


class TestDag:
    def test_topo_order(self):
        jobs = [_job("c", deps=["b"]), _job("a"), _job("b", deps=["a"])]
        assert validate_dag(jobs) == ["a", "b", "c"]

    def test_cycle_rejected(self):
        with pytest.raises(DagError) as e:
            validate_dag([_job("a", deps=["b"]), _job("b", deps=["a"])])
        assert e.value.code == "cycle"

    def test_unmet_and_self_and_dup(self):
        with pytest.raises(DagError) as e:
            validate_dag([_job("a", deps=["ghost"])])
        assert e.value.code == "unmet_dependency"
        with pytest.raises(DagError):
            validate_dag([_job("a", deps=["a"])])
        with pytest.raises(DagError):
            validate_dag([_job("a"), _job("a")])

    def test_blocked_descendants(self, sched):
        sched.submit_plan([_job("root"), _job("mid", deps=["root"]),
                           _job("leaf", deps=["mid"]),
                           _job("other")])
        claim = sched.claim("dispatch")
        assert claim["id"] == "root"
        sched.fail("root", claim["fencing_token"], "boom")
        snap = sched.status_snapshot()
        st = {j["id"]: j["status"] for j in snap["jobs"]}
        assert st["mid"] == "blocked" and st["leaf"] == "blocked"
        assert st["other"] == "ready"
        reasons = {j["id"]: j["blocked_reason"] for j in snap["jobs"]}
        assert "root" in reasons["mid"]


class TestCapacity:
    def test_jimeng_five_slots_global(self, tmp_path):
        db = Database(tmp_path / "f.db")
        s1 = Scheduler(db, worker_id="w1")
        s2 = Scheduler(db, worker_id="w2")   # second worker, same DB
        s1.submit_plan([_job(f"j{i}") for i in range(8)])
        claimed = []
        for _ in range(5):
            c = s1.claim("dispatch") or s2.claim("dispatch")
            if c:
                claimed.append(c)
        assert len(claimed) == 5
        assert s1.claim("dispatch") is None   # 6th hits the global cap
        snap = s1.status_snapshot()
        assert snap["capacities"]["jimeng_submit"]["used"] == 5
        db.close()

    def test_vertex_single_slot(self, sched):
        sched.submit_plan([_job("v1", "generate_vertex"),
                           _job("v2", "generate_vertex")])
        assert sched.claim("dispatch")["id"] == "v1"
        assert sched.claim("dispatch") is None

    def test_render_single_slot_and_release(self, sched):
        sched.submit_plan([_job("r1", "render"), _job("r2", "render")])
        c = sched.claim("dispatch")
        assert c["phase"] == "render"
        assert sched.claim("dispatch") is None
        sched.complete("r1", c["fencing_token"])
        c2 = sched.claim("dispatch")
        assert c2["id"] == "r2"


class TestLeasesAndFencing:
    def test_completion_requires_fencing(self, sched):
        sched.submit_plan([_job("a")])
        c = sched.claim("dispatch")
        with pytest.raises(FencingError) as e:
            sched.complete("a", c["fencing_token"] + 99)
        assert e.value.code == "stale_fencing"

    def test_other_worker_cannot_complete(self, sched, tmp_path):
        sched.submit_plan([_job("a")])
        c = sched.claim("dispatch")
        other = Scheduler(sched.db, worker_id="w2")
        with pytest.raises(FencingError):
            other.complete("a", c["fencing_token"])

    def test_reclaim_expired_keeps_unfinished_hold(self, sched):
        sched.submit_plan([_job("a")])
        c = sched.claim("dispatch")
        # Mark the job as if it has an unfinished remote attempt.
        sched.db.conn.execute(
            "UPDATE jobs SET status='accepted', lease_expires='2000-01-01'"
            " WHERE id='a'")
        sched.db.conn.execute(
            "INSERT INTO attempts(id,job_id,attempt_seq,status,body,"
            "created_at,updated_at) VALUES('at:1','a',1,'running','{}',"
            "'x','x')")
        reclaimed = sched.reclaim_expired()
        assert reclaimed == ["a"]
        # Job is claimable again but the capacity hold is retained.
        snap = sched.status_snapshot()
        assert snap["capacities"]["jimeng_submit"]["used"] == 1


class TestPauseDrain:
    def test_pause_stops_dispatch_only(self, sched):
        sched.submit_plan([_job("gen"), _job("obs", "observe")])
        sched.db.conn.execute(
            "UPDATE jobs SET status='accepted' WHERE id='obs'")
        sched.pause()
        assert sched.claim("dispatch") is None
        obs = sched.claim("observe")
        assert obs["id"] == "obs"          # collection continues
        sched.resume()
        assert sched.claim("dispatch")["id"] == "gen"

    def test_drain_blocks_new(self, sched):
        sched.submit_plan([_job("a")])
        sched.drain()
        assert sched.claim("dispatch") is None
        sched.undrain()
        assert sched.claim("dispatch") is not None


class TestResourceGate:
    def test_low_disk_blocks_render_only(self, sched):
        sched.resources = ResourcePolicy(min_free_bytes=1 << 40,
                                         probe=lambda: 0)
        sched.submit_plan([_job("gen"), _job("r", "render")])
        c = sched.claim("dispatch")
        assert c["phase"] != "render" or c["id"] == "gen"
        assert sched.claim("dispatch") is None   # render hits the gate
        snap = sched.status_snapshot()
        render = next(j for j in snap["jobs"] if j["id"] == "r")
        assert render["status"] == "ready"
        assert "resource_gate" in (render["blocked_reason"] or "")
