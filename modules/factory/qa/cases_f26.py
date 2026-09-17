"""F26 manual scenarios: shared-runtime cleanup, identity conflicts,
upload-failure recovery sweep, and full-completion resource audit."""
import json

from .cases_f01 import CaseContext, _result
from ..resources import CleanupService, ResourceRegistry
from ..store import Database


class _FakeOS:
    """Simulated kernel view used by all F26 scenarios."""

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

    def spawn(self, pid, command, birth=None):
        self.table[pid] = {"pid": pid, "ppid": 1,
                           "birth": birth or f"birth{pid}",
                           "command": command}


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    reg = ResourceRegistry(db)
    os_ = _FakeOS()
    svc = CleanupService(reg, table_fn=os_.table_fn,
                         kill_fn=os_.kill_fn, port_fn=os_.port_fn,
                         sleep_fn=lambda s: None)
    return db, reg, os_, svc


def _own(reg, os_, rid, pid, owner, cls="per_job", holders=(),
         ports=(), command="ffmpeg -i x"):
    os_.spawn(pid, command)
    reg.register(rid, pid, os_.table[pid]["birth"], command, owner,
                 cls=cls, holders=holders, ports=ports)


def f26_m01(ctx: CaseContext):
    """A finishes while B shares a runtime; cleanup stops A-only
    resources, frees A's ports, and leaves B + dashboard running."""
    _, reg, os_, svc = _stack(ctx, "m01")
    _own(reg, os_, "a-render", 100, "expA", ports=(8123,))
    _own(reg, os_, "a-preview", 101, "expA", ports=(8124,))
    _own(reg, os_, "shared-rt", 200, "expA", cls="shared",
         holders=("expA", "expB"), command="hypit serve",
         ports=(9000,))
    _own(reg, os_, "b-render", 300, "expB", ports=(8125,))
    _own(reg, os_, "dashboard", 400, "app", cls="application",
         command="uvicorn app", ports=(8500,))
    for pid, port in ((100, 8123), (101, 8124), (300, 8125),
                      (400, 8500)):
        os_.listeners[port] = pid
    r = svc.cleanup("expA")
    checks = {
        "a_only_stopped": 100 not in os_.table and 101 not in os_.table,
        "a_ports_free": 8123 not in os_.listeners
        and 8124 not in os_.listeners,
        "shared_retained": 200 in os_.table
        and reg.get("shared-rt")["holders"] == ["expB"],
        "b_uninterrupted": 300 in os_.table
        and os_.listeners.get(8125) == 300,
        "dashboard_uninterrupted": 400 in os_.table
        and os_.listeners.get(8500) == 400,
        "receipt_verified": r["state"] == "verified",
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f26_m02(ctx: CaseContext):
    """Recorded PID is now an unrelated process and the port is held
    independently — nothing is killed; the conflict is reported."""
    _, reg, os_, svc = _stack(ctx, "m02")
    reg.register("old-render", 100, "birth-old", "ffmpeg -i x", "expA",
                 ports=(8123,))
    os_.spawn(100, "unrelated-daemon", birth="birth-new")
    os_.spawn(999, "nginx")
    os_.listeners[8123] = 999
    r = svc.cleanup("expA")
    checks = {
        "unrelated_pid_alive": 100 in os_.table
        and os_.table[100]["command"] == "unrelated-daemon",
        "port_holder_alive": 999 in os_.table,
        "nothing_killed": not os_.killed,
        "conflict_reported": r["port_conflicts"] == [8123],
        "blocked_not_clean": r["state"] == "blocked",
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f26_m03(ctx: CaseContext):
    """Upload failed after rendering; a restarted worker reaps idle
    render processes while final/transfer state is retained and the
    later upload resumes without rerendering."""
    db, reg, os_, svc = _stack(ctx, "m03")
    _own(reg, os_, "render-proc", 100, "expA")
    final = ctx.run_dir / "final.mp4"
    final.write_bytes(b"final")
    delivery = ctx.run_dir / "delivery.json"
    delivery.write_text(json.dumps({"status": "failed"}))
    # "restart": fresh service, same registry — sweep stale owned procs
    svc2 = CleanupService(reg, table_fn=os_.table_fn,
                          kill_fn=os_.kill_fn, port_fn=os_.port_fn,
                          sleep_fn=lambda s: None)
    r = svc2.reap_stale("expA")
    checks = {
        "idle_render_cleaned": "render-proc" in r["reaped"]
        and 100 not in os_.table,
        "final_retained": final.exists(),
        "transfer_state_retained": delivery.exists(),
        "no_rerender_needed": reg.get("render-proc")["status"]
        == "stopped",
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f26_m04(ctx: CaseContext):
    """All variants complete: no idle per-video worker or listener
    remains; shared/app services are listed intentionally; the
    cleanup receipt supports the claim."""
    _, reg, os_, svc = _stack(ctx, "m04")
    for i, v in enumerate("ABCD"):
        _own(reg, os_, f"{v}-render", 100 + i, f"exp{v}",
             ports=(8200 + i,))
        os_.listeners[8200 + i] = 100 + i
    _own(reg, os_, "dashboard", 400, "app", cls="application",
         command="uvicorn app", ports=(8500,))
    _own(reg, os_, "worker", 500, "app", cls="application",
         command="factory worker", ports=())
    os_.listeners[8500] = 400
    receipts = {v: svc.cleanup(f"exp{v}") for v in "ABCD"}
    view = svc.inspect()
    checks = {
        "all_cleaned": all(r["state"] == "verified"
                           for r in receipts.values()),
        "no_idle_per_video": not any(
            100 + i in os_.table for i in range(4)),
        "no_per_video_listeners": not any(
            8200 + i in os_.listeners for i in range(4)),
        "app_services_listed": 400 in os_.table and 500 in os_.table,
        "app_port_intentional": os_.listeners.get(8500) == 400,
        "receipts_recorded": all(r["stopped"] for r in
                                 receipts.values()),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def implementations():
    return {"F26-M01": f26_m01, "F26-M02": f26_m02,
            "F26-M03": f26_m03, "F26-M04": f26_m04}
