"""Startup reconciliation gate (F30): unfinished attempts (remote
effects without a terminal outcome) must reconcile BEFORE new paid
dispatch — a restart or restore never re-spends by accident.
"""


def dispatch_gate(db):
    """→ {allowed, unresolved, reason}."""
    attempts = db.uow().attempts.unfinished()
    jobs = db.uow().conn.execute(
        "SELECT id,status FROM jobs WHERE status IN "
        "('reserved','dispatching','accepted','running','unknown','cancel_requested')"
    ).fetchall()
    unresolved = [{"attempt": a["id"], "status": a["status"]}
                  for a in attempts] + \
                 [{"job": j["id"], "status": j["status"]} for j in jobs]
    hold = db.conn.execute("SELECT value FROM meta WHERE key='restore_pending'").fetchone()
    issues = db.conn.execute("SELECT COUNT(*) FROM migration_issues WHERE resolved_evidence IS NULL").fetchone()[0]
    if hold:
        unresolved.append({"restore": "requires_verified_activation"})
    if issues:
        unresolved.append({"migration_issues": issues})
    return {"allowed": not unresolved,
            "unresolved": unresolved,
            "reason": "reconcile external history first"
            if unresolved else ""}


def activation_gate(db):
    """After a RESTORE: dispatch stays gated until the external
    effects recorded in the backup are reconciled — ledger and
    receipts must be trusted before spend headroom opens."""
    gate = dispatch_gate(db)
    pending = len(gate["unresolved"])
    return {"dispatch_enabled": pending == 0,
            "pending_effects": pending,
            "action": "run reconcile against provider remote state"
            if pending else "ready"}


def activate_restore(db, artifacts, evidence):
    """Review restored bytes and terminal receipts, then retire ALL old authority.

    Evidence records the operator's external account/charge audit. Activation
    restores usability, not money: funding and approvals must be newly issued.
    """
    import json
    from datetime import datetime,timezone
    from ..domain.errors import ContractError
    from ..domain.records import content_hash
    from ..events.redact import redact
    from ..store.uow import utcnow
    pending=db.conn.execute("SELECT value FROM meta WHERE key='restore_pending'").fetchone()
    if not pending:raise ContractError('not_restored','activation')
    if not isinstance(evidence,dict) or redact(evidence)!=evidence:
        raise ContractError('invalid_reconciliation_evidence','evidence')
    if not evidence.get('reviewer') or not evidence.get('external_audit_reference') or evidence.get('backup_at')!=pending[0]:
        raise ContractError('restore_audit_required','evidence')
    try:
        through=datetime.fromisoformat(evidence['financial_activity_through'].replace('Z','+00:00'))
        backed=datetime.fromisoformat(pending[0].replace('Z','+00:00'))
        now=datetime.now(timezone.utc)
        if not backed<=through<=now or (now-through).total_seconds()>3600:raise ValueError()
    except (KeyError,ValueError,TypeError):raise ContractError('current_financial_audit_required','financial_activity_through') from None
    unresolved=[x for x in dispatch_gate(db)['unresolved'] if 'restore' not in x]
    if unresolved:raise ContractError('restore_unresolved','effects',json.dumps(unresolved))
    for row in db.conn.execute('SELECT id FROM artifacts'):
        artifacts.verified_path(row['id'])
    with db.uow() as u:
        # No historical approval or budget becomes fresh authority. The original
        # records remain immutable evidence; retirement is an independent marker.
        for kind,query in [('budget','SELECT id FROM budgets'),('authorization',"SELECT DISTINCT id FROM records WHERE kind='authorization'")]:
            for row in u.conn.execute(query).fetchall():
                u.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('retired:'+kind+':'+row['id'],pending[0]))
        digest=content_hash(evidence)
        u.conn.execute("INSERT OR REPLACE INTO meta VALUES('restore_activation',?)",(json.dumps({'evidence':evidence,'hash':digest,'at':utcnow()}),))
        u.conn.execute("DELETE FROM meta WHERE key='restore_pending'")
        u.events.append('factory:restore','activated_without_spending_authority',{'evidence_hash':digest,'reviewer':evidence['reviewer']})
    return {'activated':True,'new_funding_required':True,'new_approvals_required':True,'evidence_hash':digest}
