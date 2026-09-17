"""Owned service lifecycle (F30): API and worker start as separately
owned processes with identity registration, port preflight, health
checks and deliberate drain-vs-stop. An occupied port reports or
switches to a configured alternative — never kills the listener.
"""
import json
import subprocess
from datetime import datetime, timezone

from ..domain.errors import ContractError
from ..resources.service import scan_listeners, _kill


def _now():
    return datetime.now(timezone.utc).isoformat()


class ServiceManager:
    def __init__(self, registry, spawn_fn=None, port_fn=scan_listeners,
                 health_fn=None, table_fn=None):
        self.reg = registry
        self.spawn = spawn_fn or self._spawn
        self.listeners = port_fn
        self.health_fn = health_fn
        self.table = table_fn

    def _spawn(self, argv, workspace):
        import os, signal as s
        p = subprocess.Popen(argv, cwd=workspace,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
        return {"pid": p.pid}

    def _birth(self, pid):
        from ...batch.local import process_table
        row = process_table().get(pid)
        return row["birth"] if row else "unknown"

    def _command(self, pid):
        from ...batch.local import process_table
        row = process_table().get(pid)
        return row["command"] if row else " ".join(["unknown"])

    # --------------------------------------------------------- start --

    def start(self, name, argv, workspace, port, alternatives=(),
              cls="application"):
        """Start an owned service. If `port` is held by a process we
        do not own, try configured alternatives or fail clearly —
        the foreign listener is never touched. Idempotent: a live
        service we already own returns its record unchanged."""
        from ...batch.local import process_table, same_process
        table = self.table() if self.table else process_table()
        mine = self.reg.get(f"service-{name}")
        if mine and same_process(mine, table.get(mine["pid"])):
            return {"service": name, "pid": mine["pid"],
                    "port": mine["ports"][0] if mine["ports"] else None,
                    "state": "already_running", "at": _now()}
        listeners = self.listeners()
        chosen = None
        for cand in [port, *alternatives]:
            if cand not in listeners:
                chosen = cand
                break
            holder = listeners[cand]
            if mine and mine["pid"] == holder:
                chosen = cand          # already ours — idempotent
                break
        if chosen is None:
            raise ContractError(
                "port_occupied", "port",
                f"{port} and alternatives {alternatives} are held by "
                "processes we do not own — configure another port")
        argv = [a.replace("{port}", str(chosen)) for a in argv]
        info = self.spawn(argv, workspace)
        pid = info["pid"]
        self.reg.register(
            f"service-{name}", pid, self._birth(pid),
            self._command(pid), "app", workspace=workspace,
            ports=(chosen,), cls=cls)
        return {"service": name, "pid": pid, "port": chosen,
                "state": "started", "at": _now()}

    def health(self, name):
        res = self.reg.get(f"service-{name}")
        if res is None:
            return {"service": name, "state": "absent"}
        from ...batch.local import process_table, same_process
        table = self.table() if self.table else process_table()
        alive = same_process(res, table.get(res["pid"]))
        return {"service": name, "pid": res["pid"],
                "state": "running" if alive else "dead",
                "ports": res["ports"]}

    # ---------------------------------------------------------- stop --

    def stop(self, name, kill_fn=_kill):
        """Immediate, deliberate stop of THIS service only."""
        res = self.reg.get(f"service-{name}")
        if res is None:
            return {"service": name, "state": "absent"}
        from ...batch.local import process_table, same_process
        import signal
        if same_process(res, process_table().get(res["pid"])):
            kill_fn(res["pid"], signal.SIGTERM)
        self.reg.set_status(f"service-{name}", "stopped")
        return {"service": name, "state": "stopped", "at": _now()}

    def drain(self, scheduler):
        """Drain: stop NEW dispatch, let accepted work finish —
        reservations and remote IDs persist for reconciliation."""
        scheduler.drain()
        return {"state": "draining", "at": _now()}

    def status(self):
        out = {}
        for r in self.reg.active():
            if r["id"].startswith("service-"):
                out[r["id"][8:]] = self.health(r["id"][8:])
        return out
