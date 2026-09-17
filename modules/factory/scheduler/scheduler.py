"""Dependency scheduler, capacities and leases (F06).

Claim classes are separate: dispatch (new submissions, paused by pause),
observe (accepted/running remote ops), collect (output_available →
download). Pause stops only dispatch. Capacities are global rows so
limits hold across workers and experiments. An accepted-but-unfinished
remote operation retains its capacity hold when the job lease expires —
capacity is conservatively held until reconciliation (checklist 3/7).
"""
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from ..domain.errors import ContractError
from .graph import validate_dag, dependents

LEASE_S = 120
CAPACITIES = {"jimeng_submit": 5, "vertex_submit": 1,
              "local_render": 1, "download": 4, "dispatch": 4,
              "observe": 8}

# job phase -> capacity pool
PHASE_CAPACITY = {
    "generate_jimeng": "jimeng_submit",
    "generate_vertex": "vertex_submit",
    "tts": "jimeng_submit",        # shares the paid-generation pool shape
    "music": "jimeng_submit",
    "render": "local_render",
    "deliver": "download",
    "publish": "dispatch",
    "observe": "observe",
    "collect": "download",
    "analyze": "dispatch",
    "plan": "dispatch",
    "review": "dispatch",
    "decide": "dispatch",
    "seed": "dispatch",
    "product": "dispatch",
}

OBSERVING = ("accepted", "running", "unknown")
COLLECTABLE = ("output_available",)


class FencingError(ContractError):
    pass


class ResourcePolicy:
    """Gate new heavy local work on disk/memory; injectable for tests."""

    def __init__(self, min_free_bytes=1 << 30, probe=None):
        self.min_free_bytes = min_free_bytes
        self._probe = probe or (lambda: shutil.disk_usage("/").free)

    def ok(self):
        free = self._probe()
        if free < self.min_free_bytes:
            return False, f"disk_free {free} < {self.min_free_bytes}"
        return True, ""


class Scheduler:
    def __init__(self, db, worker_id=None, lease_s=LEASE_S,
                 resource_policy=None):
        self.db = db
        self.worker_id = worker_id or f"worker:{uuid.uuid4().hex[:8]}"
        self.lease_s = lease_s
        self.resources = resource_policy or ResourcePolicy()
        with self.db.uow() as u:
            for name, n in CAPACITIES.items():
                u.conn.execute(
                    "INSERT OR IGNORE INTO capacities(name,limit_n) "
                    "VALUES(?,?)", (name, n))

    # ------------------------------------------------------------- flags

    def _flag(self, key):
        row = self.db.conn.execute(
            "SELECT value FROM scheduler_flags WHERE key=?",
            (key,)).fetchone()
        return row and row[0] == "1"

    def _set_flag(self, key, on):
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT OR REPLACE INTO scheduler_flags(key,value) "
                "VALUES(?,?)", (key, "1" if on else "0"))
            u.events.append("scheduler", "flag",
                            {"key": key, "on": bool(on)})

    def pause(self):    self._set_flag("paused", True)
    def resume(self):   self._set_flag("paused", False)
    def drain(self):    self._set_flag("draining", True)
    def undrain(self):  self._set_flag("draining", False)

    @property
    def paused(self):
        return self._flag("paused")

    # ---------------------------------------------------------- planning

    def submit_plan(self, jobs):
        """Validate the DAG (including already-persisted jobs a new node
        may depend on), then insert the NEW jobs waiting_dependencies.
        Cycle/unmet-dep → DagError before any row is written."""
        new = list(jobs)
        new_ids = {j.id for j in new}
        persisted = self.db.conn.execute(
            "SELECT id, depends_on FROM jobs").fetchall()
        from types import SimpleNamespace
        graph_nodes = new + [SimpleNamespace(
            id=r["id"], depends_on=json.loads(r["depends_on"] or "[]"))
            for r in persisted if r["id"] not in new_ids]
        order = validate_dag(graph_nodes)
        with self.db.uow() as u:
            for jid in order:
                if jid not in new_ids:
                    continue
                job = next(j for j in new if j.id == jid)
                job.status = "waiting_dependencies"
                u.jobs.put(job)
            u.events.append("scheduler", "plan_accepted",
                            {"jobs": [j for j in order if j in new_ids],
                             "count": len(new_ids)})
        return [j for j in order if j in new_ids]

    def _deps_satisfied(self, u, job_row):
        deps = json.loads(job_row["depends_on"] or "[]")
        for dep in deps:
            row = u.conn.execute("SELECT status FROM jobs WHERE id=?",
                                 (dep,)).fetchone()
            if row is None or row["status"] != "succeeded":
                return False
        return True

    def _propagate_ready(self, u):
        """Waiting jobs whose deps all succeeded become ready."""
        rows = u.conn.execute(
            "SELECT * FROM jobs WHERE status='waiting_dependencies'"
        ).fetchall()
        promoted = []
        for r in rows:
            if self._deps_satisfied(u, r):
                u.conn.execute(
                    "UPDATE jobs SET status='ready', updated_at=? "
                    "WHERE id=?",
                    (_now(), r["id"]))
                promoted.append(r["id"])
        return promoted

    def _block_descendants(self, u, job_id, reason):
        rows = {r["id"]: r for r in u.conn.execute(
            "SELECT id, depends_on FROM jobs").fetchall()}
        children = {k: [] for k in rows}
        for jid, r in rows.items():
            for d in json.loads(r["depends_on"] or "[]"):
                children.setdefault(d, []).append(jid)
        stack, seen = [job_id], set()
        blocked = []
        while stack:
            cur = stack.pop()
            for child in children.get(cur, []):
                if child in seen:
                    continue
                seen.add(child)
                blocked.append(child)
                stack.append(child)
        for jid in blocked:
            u.conn.execute(
                "UPDATE jobs SET status='blocked', blocked_reason=?, "
                "updated_at=? WHERE id=? AND status NOT IN "
                "('succeeded','failed','cancelled')",
                (f"ancestor {job_id}: {reason}", _now(), jid))
        return blocked

    # --------------------------------------------------------- capacity

    def _capacity_free(self, u, capacity):
        row = u.conn.execute("SELECT limit_n FROM capacities WHERE name=?",
                             (capacity,)).fetchone()
        if row is None:
            raise ContractError("unknown_capacity", "capacity", capacity)
        now = _now()
        used = u.conn.execute(
            "SELECT COUNT(*) FROM capacity_holds WHERE capacity=? AND "
            "expires_at>?", (capacity, now)).fetchone()[0]
        return row[0] - used

    def _hold(self, u, capacity, job_id, expires):
        u.conn.execute(
            "INSERT OR REPLACE INTO capacity_holds(capacity,job_id,"
            "holder,fencing,expires_at) VALUES(?,?,?,?,?)",
            (capacity, job_id, self.worker_id, 0,
             expires.isoformat() + "Z"))

    def _release_holds(self, u, job_id, keep_unfinished=True):
        if keep_unfinished:
            has_unfinished = u.conn.execute(
                "SELECT COUNT(*) FROM attempts WHERE job_id=? AND status "
                "IN ('dispatching','accepted','running','unknown')",
                (job_id,)).fetchone()[0]
            if has_unfinished:
                u.conn.execute(
                    "UPDATE capacity_holds SET retained_reason="
                    "'unfinished_remote_op' WHERE job_id=?", (job_id,))
                return
        u.conn.execute("DELETE FROM capacity_holds WHERE job_id=?",
                       (job_id,))

    # ------------------------------------------------------------ claim

    def claim(self, queue="dispatch"):
        """Claim the next eligible job for this worker.
        queue: dispatch | observe | collect."""
        if queue == "dispatch" and (self.paused or self._flag("draining")):
            return None
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.lease_s)
        with self.db.uow() as u:
            self._propagate_ready(u)
            if queue == "dispatch":
                want = "ready"
            elif queue == "observe":
                want = None            # claims by status below
            else:
                want = None
            candidates = u.conn.execute(
                "SELECT * FROM jobs WHERE status IN "
                + ("('ready')" if queue == "dispatch" else
                   "('accepted','running','unknown')" if queue == "observe"
                   else "('output_available')")
                + " AND (lease_expires IS NULL OR lease_expires<?) "
                "ORDER BY created_at", (_now(),)).fetchall()
            for row in candidates:
                capacity = PHASE_CAPACITY.get(row["phase"])
                if capacity and self._capacity_free(u, capacity) <= 0:
                    continue
                if queue == "dispatch" and capacity == "local_render":
                    ok, reason = self.resources.ok()
                    if not ok:
                        u.conn.execute(
                            "UPDATE jobs SET blocked_reason=? WHERE id=?",
                            (f"resource_gate: {reason}", row["id"]))
                        continue
                fencing = row["fencing_token"] + 1
                u.conn.execute(
                    "UPDATE jobs SET lease_owner=?, lease_expires=?, "
                    "fencing_token=?, status=?, blocked_reason=NULL, "
                    "updated_at=?, version=version+1 WHERE id=?",
                    (self.worker_id, expires.isoformat() + "Z", fencing,
                     {"dispatch": "reserved",
                      "observe": row["status"],
                      "collect": "output_available"}[queue],
                     _now(), row["id"]))
                if capacity:
                    self._hold(u, capacity, row["id"], expires)
                u.events.append(f"job:{row['id']}", "claimed",
                                {"worker": self.worker_id,
                                 "queue": queue, "fencing": fencing})
                return dict(row, fencing_token=fencing,
                            lease_owner=self.worker_id)
        return None

    # ------------------------------------------------------ completion

    def _verify_lease(self, u, job_id, fencing):
        row = u.conn.execute("SELECT * FROM jobs WHERE id=?",
                             (job_id,)).fetchone()
        if row is None:
            raise ContractError("unknown_job", "job_id", job_id)
        if row["lease_owner"] != self.worker_id \
                or row["fencing_token"] != fencing:
            raise FencingError("stale_fencing", job_id,
                               f"owner={row['lease_owner']} "
                               f"token={row['fencing_token']}")
        if row["lease_expires"] and row["lease_expires"] < _now():
            raise FencingError("lease_expired", job_id)
        return row

    def complete(self, job_id, fencing):
        with self.db.uow() as u:
            self._verify_lease(u, job_id, fencing)
            u.conn.execute(
                "UPDATE jobs SET status='succeeded', updated_at=?, "
                "version=version+1 WHERE id=?", (_now(), job_id))
            self._release_holds(u, job_id)
            u.events.append(f"job:{job_id}", "succeeded",
                            {"worker": self.worker_id})
            return self._propagate_ready(u)

    def fail(self, job_id, fencing, reason, retryable=False):
        with self.db.uow() as u:
            row = self._verify_lease(u, job_id, fencing)
            status = "ready" if retryable else "failed"
            u.conn.execute(
                "UPDATE jobs SET status=?, blocked_reason=?, "
                "lease_owner=NULL, lease_expires=NULL, updated_at=?, "
                "version=version+1 WHERE id=?",
                (status, reason, _now(), job_id))
            self._release_holds(u, job_id)
            u.events.append(f"job:{job_id}", "failed" if not retryable
                            else "retry", {"reason": reason})
            if not retryable:
                return self._block_descendants(u, job_id, reason)
        return []

    def transition(self, job_id, fencing, status):
        """Worker-verified state move (e.g. reserved→dispatching)."""
        with self.db.uow() as u:
            self._verify_lease(u, job_id, fencing)
            u.conn.execute(
                "UPDATE jobs SET status=?, updated_at=?, "
                "version=version+1 WHERE id=?", (status, _now(), job_id))
            u.events.append(f"job:{job_id}", "transition",
                            {"to": status})

    # --------------------------------------------------------- recovery

    def reclaim_expired(self):
        """Return expired-lease jobs to ready; unfinished remote ops keep
        their capacity hold (retained_reason) until reconciled."""
        now = _now()
        with self.db.uow() as u:
            rows = u.conn.execute(
                "SELECT id, status FROM jobs WHERE lease_expires IS NOT "
                "NULL AND lease_expires<? AND status IN ('reserved',"
                "'dispatching','accepted','running','output_available',"
                "'downloaded','awaiting_review','unknown')",
                (now,)).fetchall()
            reclaimed = []
            for r in rows:
                u.conn.execute(
                    "UPDATE jobs SET lease_owner=NULL, lease_expires=NULL,"
                    " status=CASE WHEN status IN ('accepted','running',"
                    "'output_available','unknown') THEN status ELSE "
                    "'ready' END, updated_at=?, version=version+1 "
                    "WHERE id=?", (now, r["id"]))
                self._release_holds(u, r["id"], keep_unfinished=True)
                u.events.append(f"job:{r['id']}", "lease_reclaimed",
                                {"by": self.worker_id})
                reclaimed.append(r["id"])
        return reclaimed

    def status_snapshot(self):
        jobs = [dict(r) for r in self.db.conn.execute(
            "SELECT id,phase,status,lease_owner,fencing_token,"
            "blocked_reason FROM jobs ORDER BY created_at").fetchall()]
        holds = [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM capacity_holds WHERE expires_at>?",
            (_now(),)).fetchall()]
        caps = {r["name"]: r["limit_n"] for r in self.db.conn.execute(
            "SELECT * FROM capacities").fetchall()}
        used = {}
        for h in holds:
            used[h["capacity"]] = used.get(h["capacity"], 0) + 1
        return {"jobs": jobs, "capacities":
                {k: {"limit": v, "used": used.get(k, 0)}
                 for k, v in caps.items()},
                "paused": self.paused,
                "draining": self._flag("draining")}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
