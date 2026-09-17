"""Health signals (F08 checklist 6): every alert names an actionable
owner and state — never a bare 'something is wrong'."""
import shutil
from datetime import datetime, timezone

def health_report(db, now=None, stale_ready_s=3600, unknown_older_s=900,
                  min_free_bytes=1 << 30, path="/"):
    now = now or datetime.now(timezone.utc).isoformat()
    signals = []

    stale_leases = db.conn.execute(
        "SELECT id, lease_owner, lease_expires FROM jobs WHERE "
        "lease_expires IS NOT NULL AND lease_expires<? AND status IN "
        "('reserved','dispatching','accepted','running','output_available',"
        "'unknown')", (now,)).fetchall()
    for r in stale_leases:
        signals.append({"signal": "stale_lease", "job": r["id"],
                        "owner": r["lease_owner"], "state": "expired",
                        "action": "reclaim via scheduler.reclaim_expired"})

    unknown = db.conn.execute(
        "SELECT id, job_id, updated_at FROM attempts WHERE status="
        "'unknown'").fetchall()
    for r in unknown:
        signals.append({"signal": "unknown_attempt", "attempt": r["id"],
                        "job": r["job_id"], "owner": "operator",
                        "state": "unresolved",
                        "action": "reconcile or resolve_unknown with evidence"})

    ready = db.conn.execute(
        "SELECT id, created_at FROM jobs WHERE status='ready'").fetchall()
    for r in ready:
        age = (datetime.fromisoformat(now.replace("Z", "+00:00"))
               - datetime.fromisoformat(
                   r["created_at"].replace("Z", "+00:00"))).total_seconds()
        if age > stale_ready_s:
            signals.append({"signal": "prolonged_ready", "job": r["id"],
                            "age_s": int(age), "owner": "scheduler",
                            "state": "waiting",
                            "action": "check capacity/deps/resource gates"})

    try:
        free = shutil.disk_usage(path).free
    except OSError:
        free = 0
    if free < min_free_bytes:
        signals.append({"signal": "storage_pressure",
                        "free_bytes": free, "owner": "operator",
                        "state": "below_floor",
                        "action": "clean staging/blobs or grow volume"})

    pending = db.conn.execute(
        "SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0]
    if pending:
        signals.append({"signal": "undelivered_intents", "count": pending,
                        "owner": "worker", "state": "pending",
                        "action": "drain outbox after dispatch resumes"})

    unapproved = db.conn.execute(
        "SELECT COUNT(*) FROM records WHERE kind='authorization' AND "
        "status='draft'").fetchone()[0]
    if unapproved:
        signals.append({"signal": "unresolved_approvals",
                        "count": unapproved, "owner": "operator",
                        "state": "awaiting_human",
                        "action": "approve or revoke in dashboard"})

    return {"at": now, "ok": not signals, "signals": signals}
