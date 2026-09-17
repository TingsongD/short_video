"""Operation executor (F07): the shared effect-safety protocol every
adapter uses — video, TTS, music, upload, publish.

Lifecycle:   prepared → dispatching → accepted → running →
             succeeded/failed/unknown → downloaded
Provider state (remote truth) and local collection state are separate:
`accepted`/`running` describe the remote operation; `downloaded` is a
local collection result.

Rules encoded:
- intent + attempt + outbox land in ONE transaction before any remote call
- remote_id is saved the instant it arrives
- ambiguous submissions stay `unknown` until reconciled by identity —
  never retried blind
- resubmission requires pre_acceptance evidence or provider-verified
  idempotency on that route
- cancellation ack ≠ terminal cancel; fallback is suppressed while the
  original's acceptance/charge/cancel is unresolved
- human resolution attaches evidence; it never resets to ready
"""
import json
from datetime import datetime, timedelta, timezone

from ..domain.errors import ContractError
from ..domain.records import Attempt, Job, canonical
from ..testing.fakes import ProviderError
from ..store.uow import utcnow
from . import retry


class Executor:
    def __init__(self, db, provider=None, clock=None):
        self.db = db
        self.provider = provider
        self.clock = clock

    # ------------------------------------------------------- prepare

    def prepare(self, job_id, attempt_seq, request, kind="provider_submit",
                reservation_id=None, provider="", model="", route="",
                billing_scope="", request_hash=None, extra=None):
        """Persist intent + attempt + outbox intent atomically — BEFORE
        crossing the network boundary. Returns attempt_id."""
        # The request hash is the wire-canonical hash the provider will
        # record — sorted keys, default separators — so reconciliation by
        # hash actually finds the remote operation.
        import hashlib
        from ..events.redact import redact
        durable_request = redact(request)
        if request_hash is None:
            wire = json.dumps(request, sort_keys=True, default=str)
            request_hash = hashlib.sha256(wire.encode()).hexdigest()
        attempt_id = f"att:{job_id}:{attempt_seq}"
        intent_key = f"{kind}:{attempt_id}"
        with self.db.uow() as u:
            existing = u.conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if existing:
                old = u.conn.execute("SELECT body,kind FROM intents WHERE intent_key=?", (intent_key,)).fetchone()
                if existing["request_hash"] != request_hash or old is None:
                    raise ContractError("attempt_identity_conflict", "attempt_id", attempt_id)
                if json.loads(old["body"]).get("reservation_id") != reservation_id:
                    raise ContractError("attempt_identity_conflict", "reservation_id", attempt_id)
                return attempt_id
            # Attempts FK to jobs; ensure the parent row exists.
            if u.jobs.get(job_id) is None:
                u.jobs.put(Job(schema_version="job.v1", id=job_id,
                               created_at=utcnow(),
                               logical_key=f"auto:{job_id}",
                               phase="external", status="running"))
            u.attempts.put(Attempt(
                schema_version="attempt.v1", id=attempt_id,
                created_at=utcnow(), job_id=job_id,
                attempt_seq=attempt_seq, provider=provider, model=model,
                route=route, request_hash=request_hash,
                status="prepared", reservation_id=reservation_id or ""))
            u.intents.create(intent_key, request_hash, kind, {
                "attempt_id": attempt_id, "job_id": job_id,
                "provider": provider, "model": model, "route": route,
                "billing_scope": billing_scope,
                "reservation_id": reservation_id,
                "request": durable_request, "extra": redact(extra or {})})
            u.outbox.enqueue(intent_key, kind,
                             {"attempt_id": attempt_id})
            u.events.append(f"attempt:{attempt_id}", "prepared",
                            {"kind": kind, "request_hash": request_hash})
        return attempt_id

    def require_request(self, attempt_id, request):
        from .effects import wire_hash
        if not attempt_id:
            raise ContractError("authority_required", "attempt_id")
        row = self._attempt(attempt_id)
        if row["request_hash"] != wire_hash(request):
            raise ContractError("request_scope_mismatch", "attempt_id", attempt_id)
        return row

    # -------------------------------------------------------- submit

    def submit(self, attempt_id, call=None):
        """call() performs the adapter's remote submit and returns an op
        dict with operation_id. Classifies failures; saves remote id the
        moment it exists."""
        if call is None and "[redacted]" in json.dumps(self._intent_body(attempt_id).get("request")):
            raise ContractError("transport_material_required", "request", "resolve protected transport fields before submission")
        call = call or (lambda: self.provider.submit(
            self._intent_body(attempt_id)["request"]))
        with self.db.uow() as u:
            row = self._attempt(attempt_id)
            if row["remote_id"]:
                return {"operation_id": row["remote_id"], "status": row["status"], "reused": True}
            if row["status"] != "prepared":
                raise ContractError("attempt_unresolved", "attempt_id", attempt_id)
            if u.conn.execute("SELECT 1 FROM meta WHERE key IN ('restore_pending','spend_overrun')").fetchone():
                raise ContractError("dispatch_blocked", "reconciliation")
            if u.conn.execute("SELECT 1 FROM migration_issues WHERE resolved_evidence IS NULL").fetchone():
                raise ContractError("dispatch_blocked", "migration")
            from .effects import CONTROLLED, EffectService
            kind = u.conn.execute("SELECT kind FROM intents WHERE json_extract(body,'$.attempt_id')=?", (attempt_id,)).fetchone()[0]
            binding = None
            if kind in CONTROLLED or row["provider"] in {"jimeng_canvas", "google_vertex", "elevenlabs", "viral_outliers", "drive", "upload_post"}:
                effects = EffectService(self.db, clock=(self.clock.now if hasattr(self.clock, "now") else self.clock))
                binding = effects.preflight(attempt_id)
                assessed = effects._price(binding)
                binding = dict(binding, attempt_id=attempt_id, approved_price=({"unit": assessed.unit, "amount": assessed.reserve_amount} if assessed else None))
            u.conn.execute("UPDATE attempts SET status='dispatching',updated_at=? WHERE id=? AND status='prepared'", (utcnow(), attempt_id))
            u.events.append(f"attempt:{attempt_id}", "dispatch_started", {})
        try:
            from .context import dispatch_context
            with dispatch_context(binding):
                op = call()
        except ProviderError as e:
            cls = retry.classify(e.code, getattr(e, "http_status", None),
                                 where="submit")
            if cls == "pre_acceptance":
                self._set_status(attempt_id, "failed",
                                 "submit_failed",
                                 {"cause": e.code, "class": cls})
                reservation_id = self._attempt(attempt_id).get("reservation_id")
                if reservation_id:
                    from ..budget import BudgetService
                    BudgetService(self.db).release(reservation_id, evidence=f"verified pre-acceptance rejection:{e.code}")
            else:  # ambiguous — accepted may have happened
                self._set_status(attempt_id, "unknown",
                                 "ack_lost",
                                 {"cause": e.code, "class": cls})
            raise
        except Exception:
            self._set_status(attempt_id, "unknown", "ack_lost", {"cause": "unclassified_transport_failure"})
            raise
        if not isinstance(op, dict) or "operation_id" not in op:
            self._set_status(attempt_id, "unknown", "ack_unparseable")
            raise ContractError("malformed_ack", attempt_id,
                                "provider acknowledgement lacks an operation identity")
        status=op.get("status","accepted")
        if status not in {"accepted","running","succeeded","failed","cancelled","unknown"}:
            self._set_status(attempt_id,"unknown","ack_unparseable")
            raise ContractError("malformed_ack","status")
        self._attach_remote(attempt_id, op["operation_id"], status, "accepted")
        return op

    def _attach_remote(self, attempt_id, remote_id, status, event):
        if not isinstance(remote_id, str) or not remote_id.strip():
            raise ContractError("malformed_remote_id", "remote_id")
        with self.db.uow() as u:
            old = self._attempt(attempt_id)
            if old["remote_id"] and old["remote_id"] != remote_id:
                raise ContractError("remote_identity_conflict", "attempt_id", attempt_id)
            u.conn.execute(
                "UPDATE attempts SET remote_id=?, status=?, updated_at=? "
                "WHERE id=?", (remote_id, status, utcnow(), attempt_id))
            u.conn.execute(
                "UPDATE intents SET remote_id=?, status='dispatched' "
                "WHERE json_extract(body,'$.attempt_id')=?", (remote_id, attempt_id))
            intent = u.conn.execute("SELECT intent_key FROM intents WHERE json_extract(body,'$.attempt_id')=?", (attempt_id,)).fetchone()
            if intent:
                u.outbox.mark(intent["intent_key"], "done")
            u.events.append(f"attempt:{attempt_id}", event,
                            {"remote_id": remote_id})
            if status in {"succeeded", "downloaded", "failed", "cancelled"}:
                self._set_status(attempt_id, status, "remote_terminal_reconciled")

    def _set_status(self, attempt_id, status, event, body=None):
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE attempts SET status=?, updated_at=? WHERE id=?",
                (status, utcnow(), attempt_id))
            if status == "unknown":
                row = self._attempt(attempt_id)
                u.conn.execute("UPDATE reservations SET status='ambiguous' WHERE id=? AND status='held'", (row["reservation_id"],))
            if status in ("succeeded", "downloaded", "failed", "cancelled"):
                u.conn.execute("DELETE FROM remote_holds WHERE attempt_id=?", (attempt_id,))
                job_id = self._attempt(attempt_id)["job_id"]
                u.conn.execute("""DELETE FROM capacity_holds WHERE job_id=? AND capacity IN ('jimeng_submit','vertex_submit')
                    AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.job_id=? AND a.status IN ('prepared','dispatching','accepted','running','unknown','cancel_requested'))""", (job_id, job_id))
            u.events.append(f"attempt:{attempt_id}", event, body or {})

    def _intent_body(self, attempt_id):
        row = self.db.conn.execute(
            "SELECT body FROM intents WHERE json_extract(body,'$.attempt_id')=?",
            (attempt_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    # ---------------------------------------------------------- poll

    def poll(self, attempt_id):
        """Map remote state to attempt status. An HTTP-200 error payload
        is terminal, not success."""
        row = self._attempt(attempt_id)
        self._check_retry(attempt_id)
        if row["remote_id"] is None:
            raise ContractError("no_remote_id", attempt_id)
        try:
            op = self.provider.poll(row["remote_id"])
        except ProviderError as e:
            cls = retry.classify(e.code, where="observe")
            self._bump_retry(attempt_id, cls)
            raise
        remote_status = op.get("status")
        if remote_status == "succeeded":
            self._set_status(attempt_id, "succeeded", "provider_finished",
                             {"remote": remote_status})
        elif remote_status == "failed":
            self._set_status(attempt_id, "failed", "provider_failed",
                             {"remote": remote_status,
                              "error": (op.get("result") or {}).get("error")})
        elif remote_status in ("accepted", "running"):
            self._set_status(attempt_id, remote_status, "observed")
        elif remote_status == "cancelled":
            self._set_status(attempt_id, "cancelled", "cancelled_terminal")
        return op

    # -------------------------------------------------------- download

    def download(self, attempt_id, destination=None):
        row = self._attempt(attempt_id)
        self._check_retry(attempt_id)
        if row["status"] not in ("succeeded", "downloaded"):
            raise ContractError("output_not_available", "attempt_id", attempt_id)
        try:
            out = self.provider.download(row["remote_id"], destination)
        except ProviderError as e:
            cls = retry.classify(e.code, where="collect")
            self._bump_retry(attempt_id, cls)
            raise
        self._set_status(attempt_id, "downloaded", "downloaded",
                         {"sha256": out.get("sha256")})
        return out

    # -------------------------------------------------------- recovery

    def reconcile(self, attempt_id):
        """Look the operation up by remote_id, else by request_hash.
        Updates status from provider truth; never creates a new op."""
        row = self._attempt(attempt_id)
        body = self._intent_body(attempt_id)
        from .context import dispatch_context
        with dispatch_context({'attempt_id':attempt_id}):
            op = self.provider.reconcile(
                operation_id=row["remote_id"],
                request_hash=row["request_hash"] or body.get("request_hash"))
        if op is None:
            self._set_status(attempt_id, "unknown", "reconcile_miss")
            return None
        self._attach_remote(attempt_id, op["operation_id"],
                            op.get("status", "accepted"), "reconciled")
        return op

    def recover(self):
        """Restart scan: every unfinished attempt gets reconciled or
        stays explicitly unknown. Returns a report."""
        rows = self.db.uow().attempts.unfinished()
        report = {"reconciled": [], "still_unknown": [], "terminal": [], "prepared": []}
        for r in rows:
            if r["status"] == "prepared":
                report["prepared"].append(r["id"])
                continue
            try:
                op = self.reconcile(r["id"])
            except ProviderError:
                op = None
            if op is None:
                report["still_unknown"].append(r["id"])
            elif op.get("status") in ("failed", "cancelled"):
                report["terminal"].append(r["id"])
            else:
                report["reconciled"].append(r["id"])
        return report

    # ----------------------------------------------------- cancellation

    def request_cancel(self, attempt_id):
        """Cancellation acknowledgement is not terminal cancellation."""
        row = self._attempt(attempt_id)
        if row["remote_id"] and hasattr(self.provider, "cancel"):
            try:
                self.provider.cancel(row["remote_id"])
            except ProviderError:
                pass
        self._set_status(attempt_id, "cancel_requested",
                         "cancel_requested")
        return "cancel_requested"

    def cancel_pending(self, attempt_id):
        return self._attempt(attempt_id)["status"] in (
            "cancel_requested", "accepted", "running", "unknown")

    def fallback_allowed(self, attempt_id):
        """A competing paid fallback is suppressed while the original's
        acceptance, charge or cancellation is unresolved."""
        row = self._attempt(attempt_id)
        if row["status"] not in ("failed", "cancelled"):
            return False
        reservation = self.db.conn.execute("SELECT status FROM reservations WHERE id=?", (row["reservation_id"],)).fetchone()
        return not reservation or reservation["status"] in ("released", "settled")

    def resolve_unknown(self, attempt_id, evidence, outcome):
        """Human/operator resolution REQUIRES evidence; outcome is
        terminal (confirmed_charged | confirmed_no_effect | cancelled) —
        never a reset to ready."""
        if not evidence:
            raise ContractError("resolution_needs_evidence", "evidence")
        if outcome not in ("confirmed_charged", "confirmed_no_effect",
                           "cancelled"):
            raise ContractError("bad_resolution", "outcome", outcome)
        self._set_status(attempt_id,
                         {"confirmed_charged": "unknown",
                          "confirmed_no_effect": "failed",
                          "cancelled": "cancelled"}[outcome],
                         "human_resolution",
                         {"evidence": evidence, "outcome": outcome})

    # ------------------------------------------------------------ misc

    def _attempt(self, attempt_id):
        row = self.db.conn.execute(
            "SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row is None:
            raise ContractError("unknown_attempt", "attempt_id",
                                attempt_id)
        return dict(json.loads(row["body"]), **dict(row))

    def _check_retry(self, attempt_id):
        state = json.loads(self._attempt(attempt_id)["retry_state"] or "{}")
        if state and retry.next_action(state)["action"] == "escalate":
            raise ContractError("retry_exhausted", "attempt_id", attempt_id)
        now = self.clock.now() if hasattr(self.clock, "now") else (self.clock() if self.clock else datetime.now(timezone.utc))
        if state.get("next_retry_at") and datetime.fromisoformat(state["next_retry_at"]) > now:
            raise ContractError("retry_backoff", "attempt_id", attempt_id)

    def _bump_retry(self, attempt_id, cause):
        with self.db.uow() as u:
            row = u.conn.execute(
                "SELECT retry_state FROM attempts WHERE id=?",
                (attempt_id,)).fetchone()
            state = json.loads(row["retry_state"] or "{}")
            if state.get("cause") != cause:
                state = {"cause": cause, "retries": 0}
            state["retries"] += 1
            nxt = retry.next_action(state)
            now = self.clock.now() if hasattr(self.clock, "now") else (self.clock() if self.clock else datetime.now(timezone.utc))
            if nxt.get("wait_s") is not None:
                state["next_retry_at"] = (now + timedelta(seconds=nxt["wait_s"])).isoformat()
            u.conn.execute(
                "UPDATE attempts SET retry_state=?, updated_at=? "
                "WHERE id=?",
                (json.dumps(state), utcnow(), attempt_id))
            u.events.append(f"attempt:{attempt_id}", "retry_decision",
                            {"cause": cause, "retries": state["retries"],
                             "next": nxt})
        return state
