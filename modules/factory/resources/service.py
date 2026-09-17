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

from ...batch.local import process_table, same_process, descendants


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
            if (owner in b.get("holders", [b["owner"]]) or not b.get("holders") and b["owner"]==owner) and (b["status"]==status or status=="active" and b["status"]=="orphaned"):
                out.append({"id": rid, **b})
        return out

    def active(self):
        rows = self.db.uow().conn.execute(
            "SELECT id,body FROM records WHERE kind='resource'"
        ).fetchall()
        return [{"id": rid, **json.loads(b)}
                for rid, b in rows if json.loads(b)["status"] in ("active","orphaned")]

    def release_holder(self, resource_id, holder):
        b = self.get(resource_id)
        holders = sorted(set(b["holders"]) - {holder})
        self._set(resource_id, holders=holders, owner=b["owner"] if holders else holder,
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

    def cleanup(self, owner, now="", resource_ids=None, include_application=False):
        """Capture descendants before stopping parents; retain identities until exit is verified."""
        import hashlib
        now=now or _now(); table=self.table(); listeners_before=self.ports()
        mine=[r for r in self.reg.for_owner(owner) if resource_ids is None or r["id"] in resource_ids]
        before={"resources":len(mine),"listeners":listeners_before}
        stopped,retained,unrelated,killable=[],[],[],[]
        ports=set()
        protected={r["pid"] for r in self.reg.active() if
                   (r["cls"]=="application" and not include_application) or
                   r["cls"]=="shared" and set(r["holders"])-{owner}}
        for r in mine:
            if r["pid"] in protected:
                retained.append({"id":r["id"],"why":"application" if r["cls"]=="application" else "shared_active","holders":r["holders"]})
                if r["cls"]=="shared": self.reg.release_holder(r["id"],owner)
                continue
            ports.update(r["ports"])
            if not same_process(r,table.get(r["pid"])):
                self.reg.set_status(r["id"],"reaped")
                if r["pid"] in table:
                    unrelated.append({"pid":r["pid"],"why":"pid_reused","command":table[r["pid"]]["command"]})
                continue
            for pid in descendants(table,{r["pid"]}):
                # Registered shared/application subtrees keep their ownership.
                if any(pid in descendants(table,{p}) for p in protected): continue
                if any(k["pid"]==pid for k in killable): continue
                if pid==r["pid"]:
                    item=r
                else:
                    child=table[pid]
                    rid="child-"+hashlib.sha256(f"{r['id']}:{pid}:{child['birth']}".encode()).hexdigest()[:24]
                    if self.reg.get(rid) is None:
                        self.reg.register(rid,pid,child["birth"],child["command"],owner,
                                          workspace=r.get("workspace",""),ports=[p for p,holder in listeners_before.items() if holder==pid])
                    item={"id":rid,**self.reg.get(rid)}
                killable.append(item)
                ports.update(item["ports"])
        # Children first, then roots. Recheck each identity immediately before signalling.
        killable.sort(key=lambda r:r["id"] not in {m["id"] for m in mine},reverse=True)
        for sig in (signal.SIGTERM,signal.SIGKILL):
            pending=[r for r in killable if same_process(r,self.table().get(r["pid"]))]
            for r in pending:
                if same_process(r,self.table().get(r["pid"])): self.kill(r["pid"],sig)
            for _ in range(5):
                if not any(same_process(r,self.table().get(r["pid"])) for r in pending): break
                self.sleep(.05)
        table=self.table()
        survivors=[r["pid"] for r in killable if same_process(r,table.get(r["pid"]))]
        for r in killable:
            if r["pid"] not in survivors:
                stopped.append({"id":r["id"],"pid":r["pid"]}); self.reg.set_status(r["id"],"stopped")
        conflicts=sorted(p for p in ports if p in self.ports())
        receipt={"owner":owner,"at":now,"before":before,"stopped":stopped,"retained":retained,
                 "pid_reuse_untouched":unrelated,"survivors":survivors,"ports_checked":sorted(ports),
                 "port_conflicts":conflicts,"state":"verified" if not survivors and not conflicts else "blocked"}
        self._receipt(owner,receipt)
        return receipt

    def reap_stale(self, owner, now=""):
        result=self.cleanup(owner,now)
        return {"owner":owner,"at":result["at"],"reaped":[r["id"] for r in result["stopped"]],
                "foreign_untouched":[{"pid":r["pid"],"command":r["command"]} for r in result["pid_reuse_untouched"]],
                "state":result["state"]}

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
