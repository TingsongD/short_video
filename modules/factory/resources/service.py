"""Process ownership and resource cleanup (F26).

Resources register with identity evidence (pid + birth + command —
PID alone can be reused). Cleanup classifies per-job / shared /
application / unrelated; stops only owned idle resources; escalates
only against the SAME verified process; reports unrelated listeners
instead of killing them. Reuses modules.batch.local identity helpers.
"""
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone

from ...batch.local import process_table, same_process


def _now():
    return datetime.now(timezone.utc).isoformat()


def scan_listeners():
    """→ {port: pid} for TCP listeners (real implementation)."""
    r = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-FpFn"],
                       capture_output=True, text=True)
    out, pid = {}, None
    for line in r.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            m = re.search(r":(\d+)$", line)
            if m:
                out[int(m.group(1))] = pid
    return out


def _kill(pid, sig):
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class ResourceRegistry:
    """Durable resource records: identity evidence + owner + class."""

    def __init__(self, db):
        self.db = db

    def register(self, resource_id, pid, birth, command, owner,
                 workspace="", ports=(), cls="per_job", holders=()):
        body = {"pid": pid, "birth": birth, "command": command,
                "owner": owner, "workspace": workspace,
                "ports": sorted(set(ports)), "cls": cls,
                "holders": sorted(set(holders) or {owner}),
                "status": "active", "registered_at": _now()}
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT INTO records(kind,id,revision,schema_version,"
                "status,body,created_at,updated_at,version)"
                " VALUES('resource',?,0,'resource.v1','active',?,?,?,1)",
                (resource_id, json.dumps(body),
                 body["registered_at"], body["registered_at"]))

    def get(self, resource_id):
        row = self.db.uow().records.get("resource", resource_id)
        return json.loads(row["body"]) if row else None

    def for_owner(self, owner, status="active"):
        rows = self.db.uow().conn.execute(
            "SELECT id,body FROM records WHERE kind='resource'"
        ).fetchall()
        out = []
        for rid, body in rows:
            b = json.loads(body)
            if owner in b.get("holders", [b["owner"]]) \
                    and b["status"] == status:
                out.append({"id": rid, **b})
        return out

    def active(self):
        rows = self.db.uow().conn.execute(
            "SELECT id,body FROM records WHERE kind='resource'"
        ).fetchall()
        return [{"id": rid, **json.loads(b)}
                for rid, b in rows if json.loads(b)["status"] == "active"]

    def release_holder(self, resource_id, holder):
        b = self.get(resource_id)
        holders = sorted(set(b["holders"]) - {holder})
        self._set(resource_id, holders=holders,
                  status="active" if holders else "orphaned")

    def set_status(self, resource_id, status):
        self._set(resource_id, status=status)

    def _set(self, resource_id, **fields):
        row = self.db.uow().records.get("resource", resource_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='resource' AND "
                "id=? AND revision=?",
                (json.dumps(body), resource_id, row["revision"]))


class CleanupService:
    def __init__(self, registry, table_fn=process_table,
                 kill_fn=_kill, port_fn=scan_listeners,
                 sleep_fn=time.sleep):
        self.reg = registry
        self.table = table_fn
        self.kill = kill_fn
        self.ports = port_fn
        self.sleep = sleep_fn

    # ----------------------------------------------------- cleanup --

    def cleanup(self, owner, now=""):
        """Stop owner's idle resources; never touch shared (other
        holders), application services, or unrelated processes."""
        now = now or _now()
        table = self.table()
        mine = self.reg.for_owner(owner)
        before = {"resources": len(mine),
                  "listeners": dict(self.ports())}
        stopped, retained, unrelated = [], [], []
        killable, ports = [], set()
        for r in mine:
            ports.update(r["ports"])
            live = same_process(r, table.get(r["pid"]))
            if r["cls"] == "application":
                retained.append({"id": r["id"], "why": "application"})
            elif r["cls"] == "shared" \
                    and (set(r["holders"]) - {owner}):
                retained.append({"id": r["id"], "why": "shared_active",
                                 "holders": r["holders"]})
                self.reg.release_holder(r["id"], owner)
            elif not live:
                # dead already, or PID reused by another process —
                # identity mismatch means it is NOT ours
                self.reg.set_status(r["id"], "reaped")
                if r["pid"] in table:
                    unrelated.append({"pid": r["pid"],
                                      "why": "pid_reused"})
            else:
                killable.append(r)
        # graceful then escalate — only against same verified process
        survivors = []
        for sig in (signal.SIGTERM, signal.SIGKILL):
            table = self.table()
            pending = [r for r in killable
                       if same_process(r, table.get(r["pid"]))]
            for r in pending:
                self.kill(r["pid"], sig)
            if pending:
                self.sleep(0.05)
            survivors = pending
        table = self.table()
        survivors = [r["pid"] for r in killable
                     if same_process(r, table.get(r["pid"]))]
        for r in killable:
            if r["pid"] not in survivors:
                stopped.append({"id": r["id"], "pid": r["pid"]})
                self.reg.set_status(r["id"], "stopped")
        # port recheck — an unrelated listener is reported, never killed
        listeners = self.ports()
        conflicts = sorted(p for p in ports
                           if p in listeners
                           and listeners[p] not in
                           {r["pid"] for r in mine})
        receipt = {"owner": owner, "at": now, "before": before,
                   "stopped": stopped, "retained": retained,
                   "pid_reuse_untouched": unrelated,
                   "survivors": survivors,
                   "ports_checked": sorted(ports),
                   "port_conflicts": conflicts,
                   "state": "verified" if not survivors and not conflicts
                   else "blocked"}
        self._receipt(owner, receipt)
        return receipt

    def reap_stale(self, owner, now=""):
        """Post-crash sweep: identity-verified owned processes still
        alive are stale — stop them; mismatched PIDs are left alone."""
        now = now or _now()
        table = self.table()
        reaped, foreign = [], []
        for r in self.reg.for_owner(owner):
            cur = table.get(r["pid"])
            if same_process(r, cur):
                self.kill(r["pid"], signal.SIGTERM)
                self.sleep(0.01)
                table = self.table()
                if not same_process(r, table.get(r["pid"])):
                    self.reg.set_status(r["id"], "stopped")
                    reaped.append(r["id"])
                else:
                    self.kill(r["pid"], signal.SIGKILL)
                    self.sleep(0.01)
                    if not same_process(r, self.table().get(r["pid"])):
                        self.reg.set_status(r["id"], "stopped")
                        reaped.append(r["id"])
            elif cur is not None:
                foreign.append({"pid": r["pid"],
                                "command": cur["command"]})
                self.reg.set_status(r["id"], "reaped")
            else:
                self.reg.set_status(r["id"], "reaped")
        return {"owner": owner, "at": now, "reaped": reaped,
                "foreign_untouched": foreign}

    def inspect(self):
        """Current view: active owned resources, live ones by identity,
        and recorded ports still listening."""
        table = self.table()
        act = self.reg.active()
        live = [r["id"] for r in act
                if same_process(r, table.get(r["pid"]))]
        stale = [r["id"] for r in act
                 if r["id"] not in live]
        ports = sorted({p for r in act for p in r["ports"]})
        listeners = self.ports()
        return {"active": [r["id"] for r in act], "live": live,
                "stale": stale,
                "ports_listening": sorted(p for p in ports
                                          if p in listeners)}

    # -------------------------------------------------- completion --

    def complete(self, owner, qc_passed, delivery_status, now=""):
        """Final completion requires QC + verified delivery + cleanup —
        an accessible Drive link alone is not completion."""
        receipt = self.cleanup(owner, now=now)
        problems = []
        if not qc_passed:
            problems.append("qc_pending")
        if delivery_status != "verified":
            problems.append(f"delivery_{delivery_status}")
        if receipt["state"] != "verified":
            problems.append("cleanup_blocked")
        return {"owner": owner, "at": now or _now(),
                "complete": not problems, "problems": problems,
                "cleanup": receipt["state"]}

    def _receipt(self, owner, receipt):
        with self.reg.db.uow() as u:
            u.events.append(f"resources:{owner}", "cleanup_receipt",
                            receipt)
