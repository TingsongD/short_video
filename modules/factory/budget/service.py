"""Prices, budgets, approvals and reservations (F05).

Units are never interchangeable: Jimeng credits, other native credits and
integer USD microdollars live on separate budget rows. A reservation can
hold several lines atomically (e.g. Vertex sublimit + aggregate USD).
Held and ambiguous reservations count against caps — an ambiguous
submission never frees funds by being forgotten.

Settlement kinds are distinct: native_quote (Canvas credits),
usage_estimate (conservative local bound), reported_usage (provider
billing readback), invoice_confirmed (final truth). Only evidence-backed
terminal failure releases a hold.
"""
import json
import uuid
from datetime import datetime, timezone

from ..domain.errors import ContractError
from ..domain.money import UNITS
from ..domain.records import canonical, content_hash
from ..store.uow import utcnow

HELD = ("held", "ambiguous")


class ReservationBlocked(ContractError):
    def __init__(self, budget_id, reason):
        super().__init__("reservation_blocked", budget_id, reason)
        self.budget_id, self.reason = budget_id, reason


class AuthorizationRejected(ContractError):
    pass


def _parse_time(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class BudgetService:
    def __init__(self, db, clock=None):
        self.db = db
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------ budgets

    def create_budget(self, bid, unit, scope, scope_key="", cap=None):
        """cap=None means unset → zero authority. cap=0 blocks all spend."""
        if unit not in UNITS:
            raise ContractError("unknown_unit", "unit", unit)
        if scope not in ("aggregate", "provider", "category", "experiment"):
            raise ContractError("bad_scope", "scope", scope)
        if cap is not None and (type(cap) is not int or cap < 0):
            raise ContractError("invalid_cap", "cap_amount", repr(cap))
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT INTO budgets(id,unit,scope,scope_key,cap_amount,"
                "created_at) VALUES(?,?,?,?,?,?)",
                (bid, unit, scope, scope_key, cap, utcnow()))
        return bid

    def _committed(self, conn, budget_id):
        """Amounts held, ambiguous or already settled against a budget."""
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN r.status IN ('held','ambiguous')"
            " THEN l.amount ELSE COALESCE(l.settled_amount, l.amount) END),0)"
            " FROM reservation_lines l JOIN reservations r"
            " ON l.reservation_id=r.id WHERE l.budget_id=? AND r.status!="
            "'released'", (budget_id,)).fetchone()
        return row[0]

    def available(self, budget_id):
        row = self.db.conn.execute(
            "SELECT cap_amount FROM budgets WHERE id=?",
            (budget_id,)).fetchone()
        if row is None:
            raise ContractError("unknown_budget", "budget_id", budget_id)
        if self.db.conn.execute("SELECT 1 FROM meta WHERE key=?",("retired:budget:"+budget_id,)).fetchone():return 0
        cap = row[0]
        if cap is None:
            return 0
        return cap - self._committed(self.db.conn, budget_id)

    # --------------------------------------------------------- reservation

    def reserve(self, request_hash, lines, authorization_id=None,
                status="held"):
        """lines: [(budget_id, amount)] — all checked and held atomically.
        Returns reservation id; raises ReservationBlocked naming the cap."""
        lines = list(lines)
        if not lines or len({bid for bid, _ in lines}) != len(lines):
            raise ContractError("invalid_reservation_lines", "lines")
        if status not in HELD:
            raise ContractError("invalid_reservation_status", "status", status)
        rid = f"rsv:{uuid.uuid4().hex[:16]}"
        with self.db.uow() as u:
            # Idempotent: same request hash replays the same reservation.
            existing = u.conn.execute(
                "SELECT id, status, authorization_id FROM reservations WHERE request_hash=?",
                (request_hash,)).fetchone()
            if existing:
                old_lines = dict(u.conn.execute("SELECT budget_id,amount FROM reservation_lines WHERE reservation_id=?", (existing["id"],)).fetchall())
                if old_lines != dict(lines) or existing["authorization_id"] != authorization_id or existing["status"] == "released":
                    raise ContractError("reservation_identity_conflict", "request_hash", request_hash)
                return existing["id"]
            if u.conn.execute("SELECT 1 FROM meta WHERE key IN ('restore_pending','spend_overrun')").fetchone():
                raise ContractError("dispatch_blocked", "reconciliation")
            for budget_id, amount in lines:
                row = u.conn.execute(
                    "SELECT cap_amount FROM budgets WHERE id=?",
                    (budget_id,)).fetchone()
                if row is None:
                    raise ReservationBlocked(budget_id, "unknown_budget")
                cap = row[0]
                if cap is None:
                    raise ReservationBlocked(budget_id, "cap_unset")
                if cap == 0 and amount != 0:
                    raise ReservationBlocked(budget_id, "cap_zero")
                if type(amount) is not int or amount < 0:
                    raise ContractError("invalid_amount", budget_id,
                                        repr(amount))
                committed = self._committed(u.conn, budget_id)
                if committed + amount > cap:
                    raise ReservationBlocked(
                        budget_id,
                        f"cap_exceeded: {committed}+{amount}>{cap}")
            u.conn.execute(
                "INSERT INTO reservations(id,authorization_id,request_hash,"
                "status,created_at) VALUES(?,?,?,?,?)",
                (rid, authorization_id, request_hash, status, utcnow()))
            for budget_id, amount in lines:
                u.conn.execute(
                    "INSERT INTO reservation_lines(reservation_id,budget_id,"
                    "amount) VALUES(?,?,?)", (rid, budget_id, amount))
            u.events.append(f"reservation:{rid}", "reserved",
                            {"request_hash": request_hash,
                             "lines": dict(lines)})
        return rid

    def mark_ambiguous(self, reservation_id):
        """Acknowledgement lost — hold stays; nothing frees by forgetting."""
        with self.db.uow() as u:
            cur = u.conn.execute(
                "UPDATE reservations SET status='ambiguous' WHERE id=? "
                "AND status='held'", (reservation_id,))
            if cur.rowcount == 0:
                raise ContractError("not_held", "reservation_id",
                                    reservation_id)
            u.events.append(f"reservation:{reservation_id}",
                            "marked_ambiguous", {})

    def settle(self, reservation_id, kind, amounts, evidence=""):
        """Terminal, evidence-backed settlement. Idempotent by id.
        amounts: {budget_id: actual}. Record real charges even above the
        reservation; a variance blocks later dispatch until reconciled."""
        if kind not in ("native_quote", "usage_estimate",
                        "reported_usage", "invoice_confirmed"):
            raise ContractError("bad_settlement_kind", "kind", kind)
        with self.db.uow() as u:
            row = u.conn.execute(
                "SELECT status, authorization_id FROM reservations "
                "WHERE id=?", (reservation_id,)).fetchone()
            if row is None:
                raise ContractError("unknown_reservation", "id",
                                    reservation_id)
            saved = u.conn.execute("SELECT budget_id,settled_amount,kind FROM reservation_lines WHERE reservation_id=?", (reservation_id,)).fetchall()
            if set(amounts) != {r["budget_id"] for r in saved}:
                raise ContractError("incomplete_settlement", "amounts")
            if row["status"] == "settled":
                if any(amounts[r["budget_id"]] != r["settled_amount"] or kind != r["kind"] for r in saved):
                    raise ContractError("settlement_identity_conflict", "reservation_id", reservation_id)
                return reservation_id
            if row["status"] not in HELD:
                raise ContractError("not_held", "reservation_id", reservation_id)
            for budget_id, actual in amounts.items():
                if type(actual) is not int or actual < 0:
                    raise ContractError("invalid_amount", budget_id,
                                        repr(actual))
                line = u.conn.execute(
                    "SELECT amount FROM reservation_lines WHERE "
                    "reservation_id=? AND budget_id=?",
                    (reservation_id, budget_id)).fetchone()
                if line is None:
                    raise ContractError("unknown_line", "budget_id",
                                        budget_id)
                if actual > line["amount"]:
                    if not evidence:
                        raise ContractError("settlement_needs_evidence", "evidence")
                    u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('spend_overrun',?)",
                                   (json.dumps({"reservation": reservation_id, "budget": budget_id,
                                                "actual": actual, "reserved": line["amount"]}),))
                    u.events.append(f"reservation:{reservation_id}", "charge_variance",
                                    {"budget_id": budget_id, "actual": actual, "reserved": line["amount"]})
                u.conn.execute(
                    "UPDATE reservation_lines SET settled_amount=?, kind=? "
                    "WHERE reservation_id=? AND budget_id=?",
                    (actual, kind, reservation_id, budget_id))
            u.conn.execute(
                "UPDATE reservations SET status='settled', settled_at=?, "
                "evidence=? WHERE id=?",
                (utcnow(), evidence, reservation_id))
            u.events.append(f"reservation:{reservation_id}", "settled",
                            {"kind": kind, "amounts": amounts})
        return reservation_id

    def release(self, reservation_id, evidence=""):
        """Free a hold ONLY on evidence of a terminal no-charge outcome."""
        if not evidence:
            raise ContractError("release_needs_evidence", "evidence")
        with self.db.uow() as u:
            cur = u.conn.execute(
                "UPDATE reservations SET status='released', evidence=? "
                "WHERE id=? AND status IN ('held','ambiguous')",
                (evidence, reservation_id))
            if cur.rowcount == 0:
                raise ContractError("not_releasable", "reservation_id",
                                    reservation_id)
            u.events.append(f"reservation:{reservation_id}", "released",
                            {"evidence": evidence})

    def _headroom(self, conn, budget_id):
        row = conn.execute("SELECT cap_amount FROM budgets WHERE id=?",
                           (budget_id,)).fetchone()
        if row is None or row[0] is None:
            return 0
        return row[0] - self._committed(conn, budget_id)

    # ------------------------------------------------------- authorization

    def check_authorization(self, auth, plan_hash, provider, model,
                            request_hash, price, now=None):
        """Preflight immediately before dispatch (checklist 4).
        `auth`: Authorization record. `price`: PriceAssessment.
        Returns list of rejection reasons (empty = authorized)."""
        reasons = []
        if auth is None or getattr(auth, "status", "") != "authorized":
            return ["no_active_authorization"]
        if auth.scope_hash != plan_hash:
            reasons.append("plan_hash_mismatch")
        valid_until = _parse_time(getattr(auth, "valid_until", ""))
        if not valid_until or (now or self.clock()) >= valid_until:
            reasons.append("authorization_expired")
        if provider not in (auth.allowed_providers or []):
            reasons.append("provider_not_authorized")
        allowed_models = (auth.allowed_models or {}).get(provider, [])
        if model not in allowed_models:
            reasons.append("model_not_authorized")
        if price is None:
            reasons.append("no_price_assessment")
        else:
            if price.plan_hash and price.plan_hash != plan_hash:
                reasons.append("price_plan_mismatch")
            if price.provider != provider:
                reasons.append("price_provider_mismatch")
            if price.model and price.model != model:
                reasons.append("price_model_mismatch")
            if price.reserve_amount < price.amount:
                reasons.append("reserve_below_quote")
            if price.request_hash != request_hash:
                reasons.append("price_request_mismatch")
            if price.provisional:
                reasons.append("price_provisional")
            pexp = _parse_time(getattr(price, "valid_until", ""))
            if not pexp or (now or self.clock()) >= pexp:
                reasons.append("quote_expired")
            cap = (auth.caps or {}).get(price.unit)
            if cap is None:
                reasons.append(f"no_cap_for_unit:{price.unit}")
            elif cap is not None and price.reserve_amount > cap:
                reasons.append("price_exceeds_cap")
        return reasons

    def authorize_or_raise(self, *args, **kw):
        reasons = self.check_authorization(*args, **kw)
        if reasons:
            raise AuthorizationRejected("authorization_rejected",
                                        "preflight", "; ".join(reasons))

    # ---------------------------------------------------------- reporting

    def spend_breakdown(self):
        """Read-only per-budget view for dashboards/approvals."""
        rows = self.db.conn.execute(
            "SELECT b.id, b.unit, b.scope, b.scope_key, b.cap_amount, "
            "COALESCE(SUM(CASE WHEN r.status IN ('held','ambiguous') "
            "THEN l.amount ELSE 0 END),0) AS held, "
            "COALESCE(SUM(CASE WHEN r.status='settled' "
            "THEN l.settled_amount ELSE 0 END),0) AS settled "
            "FROM budgets b LEFT JOIN reservation_lines l ON l.budget_id=b.id "
            "LEFT JOIN reservations r ON l.reservation_id=r.id "
            "GROUP BY b.id").fetchall()
        return [dict(r) for r in rows]

    def reservations_for(self, request_hash):
        return [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM reservations WHERE request_hash=?",
            (request_hash,)).fetchall()]

    # ------------------------------------------------------- legacy import

    def import_legacy_ledger(self, path):
        """Import historical ledger.json as settled history — never as new
        authority. Idempotent by entry hash; original file untouched."""
        import hashlib
        data = json.loads(open(path, encoding="utf-8").read())
        imported, skipped = 0, 0
        with self.db.uow() as u:
            for e in data.get("entries", []):
                key = hashlib.sha256(canonical(e).encode()).hexdigest()
                try:
                    u.conn.execute(
                        "INSERT INTO ledger_imports(import_key,source_hash,"
                        "body,imported_at) VALUES(?,?,?,?)",
                        (key, hashlib.sha256(
                            open(path, "rb").read()).hexdigest(),
                         canonical(e), utcnow()))
                    imported += 1
                except Exception:                       # duplicate import
                    skipped += 1
            u.events.append("ledger", "legacy_import",
                            {"path": str(path), "imported": imported,
                             "skipped": skipped})
        return {"imported": imported, "skipped": skipped}
