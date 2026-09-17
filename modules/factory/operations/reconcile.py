"""Startup reconciliation gate (F30): unfinished attempts (remote
effects without a terminal outcome) must reconcile BEFORE new paid
dispatch — a restart or restore never re-spends by accident.
"""


def dispatch_gate(db):
    """→ {allowed, unresolved, reason}."""
    attempts = db.uow().attempts.unfinished()
    jobs = db.uow().conn.execute(
        "SELECT id,status FROM jobs WHERE status IN "
        "('dispatched','submitted','leased')"
    ).fetchall()
    unresolved = [{"attempt": a["id"], "status": a["status"]}
                  for a in attempts] + \
                 [{"job": j["id"], "status": j["status"]} for j in jobs]
    return {"allowed": not unresolved,
            "unresolved": unresolved,
            "reason": "reconcile external history first"
            if unresolved else ""}


def activation_gate(db):
    """After a RESTORE: dispatch stays gated until the external
    effects recorded in the backup are reconciled — ledger and
    receipts must be trusted before spend headroom opens."""
    pending = len(db.uow().attempts.unfinished())
    return {"dispatch_enabled": pending == 0,
            "pending_effects": pending,
            "action": "run reconcile against provider remote state"
            if pending else "ready"}
