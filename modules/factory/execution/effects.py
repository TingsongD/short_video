"""Scoped authority and atomic preparation for external effects.

Authorization binds immutable domain content and exact operation requests/quotes.
Workers reserve all applicable budget lines and remote capacity in the transaction
that creates the attempt and outbox. Observation never needs new spending authority.
"""
import hashlib
import json
from datetime import datetime, timezone

from ..budget import BudgetService
from ..domain.errors import ContractError
from ..domain.records import Authorization, PriceAssessment, content_hash
from ..store.uow import utcnow

PAID = frozenset({"generation", "analysis", "research", "tts", "music"})
ALIASES = {"tts_synthesis": "tts", "music_generation": "music", "reference_generation": "generation", "generation_submit": "generation", "discovery_search": "research", "analysis_submit": "analysis", "upload": "delivery", "publish": "publication"}
CONTROLLED = PAID | {"delivery", "publication"} | set(ALIASES)
REMOTE_CAPACITY = {"jimeng_canvas": "jimeng_submit", "google_vertex": "vertex_submit"}


def wire_hash(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


class EffectService:
    def __init__(self, db, executor=None, clock=None):
        self.db = db
        self.budget = BudgetService(db)
        self.executor = executor
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def approve(self, authorization, record_kind, record_id, operations, budget_ids):
        """Called only by an explicit approval command; never by a worker.

        Each operation has a stable key, kind/provider/model/account, request,
        and PriceAssessment for paid effects. References remain artifact IDs.
        """
        authorization.validate_or_raise()
        if not authorization.authorizing_action or not authorization.valid_until:
            raise ContractError("incomplete_authorization", "authorizing_action/valid_until")
        with self.db.uow() as u:
            for bid in budget_ids:
                if not u.conn.execute('SELECT 1 FROM budgets WHERE id=?',(bid,)).fetchone():
                    raise ContractError('budget_required','budget_id',bid)
            record = u.records.get(record_kind, record_id)
            if record is None:
                raise ContractError("not_found", "scope", record_id)
            body = json.loads(record["body"])
            plan_hash = body.get("plan_hash") or body.get("content_hash") or content_hash(body)
            if authorization.scope_hash != plan_hash:
                raise ContractError("plan_hash_mismatch", "scope_hash")
            ops = {}
            for op in operations:
                spec = dict(op)
                key = spec.pop("key")
                spec["kind"] = ALIASES.get(spec["kind"], spec["kind"])
                if spec["provider"] not in authorization.allowed_providers or spec["model"] not in authorization.allowed_models.get(spec["provider"], []):
                    raise ContractError("provider_model_not_authorized", "operation", key)
                if key in ops or spec["kind"] not in CONTROLLED or not spec.get("account"):
                    raise ContractError("invalid_operation_scope", "operation", key)
                from ..events.redact import redact
                if redact(spec["request"]) != spec["request"]:
                    raise ContractError("sensitive_request", "request", "bind stable resource identities; resolve credentials only at transport")
                price = spec.pop("price", None)
                if spec["kind"] in PAID:
                    if not isinstance(price, PriceAssessment):
                        raise ContractError("no_price_assessment", "operation", key)
                    price.validate_or_raise()
                    if price.plan_hash != plan_hash or price.model != spec["model"] or price.provider != spec["provider"] or not price.rate_basis or not price.valid_until or price.reserve_amount < price.amount:
                        raise ContractError("price_scope_mismatch", "operation", key)
                    self.budget.authorize_or_raise(authorization, plan_hash, spec["provider"], spec["model"], wire_hash(spec["request"]), price, now=self.clock())
                    u.records.put(price)
                    spec["price_id"] = price.id
                else:
                    if spec["kind"] in {"publication", "publish"} and not authorization.publication_authorized:
                        raise ContractError("publication_not_authorized", "operation", key)
                    spec["price_id"] = None
                ops[key] = spec
            if not ops:
                raise ContractError("empty_authorization", "operations")
            # Authority ceilings have dedicated budgets: several jobs cannot each
            # consume the full ceiling independently of one another.
            ids = list(budget_ids)
            for unit, cap in authorization.caps.items():
                bid = f"authority:{authorization.id}:{unit}"
                self.budget.create_budget(bid, unit, "experiment", record_id, cap)
                ids.append(bid)
            experiment = u.records.get("experimentrevision", f"exp:{body.get('experiment_id')}") if body.get("experiment_id") else None
            experiment_revision = body.get('experiment_revision', body.get('revision'))
            if record_kind == 'composition' and experiment:
                parent = u.records.get('productionplan', body.get('plan_id'))
                parent_body = json.loads(parent['body']) if parent else {}
                if (parent_body.get('experiment_id') != body.get('experiment_id')
                        or parent_body.get('plan_hash') != body.get('source_revisions', {}).get('plan_hash')
                        or parent_body.get('stale_reason')):
                    raise ContractError('stale_plan', 'composition')
                # Composition revisions and experiment revisions are separate
                # clocks. Delivery binds to the plan's experiment revision.
                experiment_revision = parent_body.get('experiment_revision')
            if experiment and experiment["revision"] != experiment_revision:
                raise ContractError("stale_plan", "experiment_revision")
            authorization.binding = {"experiment": {"id": experiment["id"], "revision": experiment["revision"], "digest": content_hash(json.loads(experiment["body"]))} if experiment else None, "kind": record_kind, "id": record_id,
                "revision": record["revision"], "plan_hash": plan_hash, "record_digest": content_hash(body),
                "operations": ops, "budget_ids": ids}
            u.records.put(authorization)
            u.events.append(f"authorization:{authorization.id}", "approved",
                            {"scope_hash": plan_hash, "operations": list(ops), "expires": authorization.valid_until})
        return authorization.id

    def _scope(self, authority_id):
        if self.db.conn.execute("SELECT 1 FROM meta WHERE key=?",("retired:authorization:"+authority_id,)).fetchone():
            raise ContractError("restored_authority_retired","authorization_id")
        row = self.db.uow().records.get("authorization", authority_id)
        if row is None:
            raise ContractError("authority_required", "authorization_id")
        auth = Authorization(**json.loads(row["body"]))
        binding = auth.binding
        if not binding or row["status"] != "authorized":
            raise ContractError("authority_required", "binding")
        experiment_binding = binding.get("experiment")
        if experiment_binding:
            exp = self.db.uow().records.get("experimentrevision", experiment_binding["id"])
            if not exp or exp["revision"] != experiment_binding["revision"] or content_hash(json.loads(exp["body"])) != experiment_binding["digest"]:
                raise ContractError("stale_authorization", "experiment_revision")
        current = self.db.uow().records.get(binding["kind"], binding["id"])
        if current is None or current["revision"] != binding["revision"]:
            raise ContractError("stale_authorization", "revision")
        body = json.loads(current["body"])
        current_hash = body.get("plan_hash") or body.get("content_hash") or content_hash(body)
        if current_hash != auth.scope_hash or content_hash(body) != binding.get("record_digest"):
            raise ContractError("stale_authorization", "plan_hash")
        if not auth.valid_until or datetime.fromisoformat(auth.valid_until.replace("Z", "+00:00")) <= self.clock():
            raise ContractError("authorization_expired", "valid_until")
        return auth

    def prepare(self, authority_id, operation_key, job_id, fencing, worker_id, attempt_seq=1):
        if self.executor is None:
            raise ContractError("executor_required", "effects")
        with self.db.uow() as u:
            auth = self._scope(authority_id)
            spec = auth.binding["operations"].get(operation_key)
            if spec is None:
                raise ContractError("operation_not_authorized", "operation_key", operation_key)
            self._lease(job_id, fencing, worker_id)
            existing = u.conn.execute("SELECT attempt_id FROM effect_bindings WHERE authorization_id=? AND operation_key=?", (authority_id, operation_key)).fetchone()
            if existing:
                attempt = u.conn.execute("SELECT job_id,status,remote_id FROM attempts WHERE id=?", (existing["attempt_id"],)).fetchone()
                if attempt["job_id"] != job_id:
                    raise ContractError("operation_identity_conflict", "job_id", job_id)
                if attempt["status"] == "prepared":
                    u.conn.execute("UPDATE effect_bindings SET worker_id=?,fencing=? WHERE attempt_id=?", (worker_id, fencing, existing["attempt_id"]))
                    return existing["attempt_id"]
                # A pre-acceptance failure never reached the provider
                # (no remote_id). Free the unique (auth, operation)
                # slot so a new attempt can be prepared after the local
                # cause is fixed. Remote-accepted attempts stay bound.
                if attempt["status"] in ("failed", "cancelled") \
                        and not attempt["remote_id"]:
                    if attempt_seq is None and not self.executor.fallback_allowed(existing['attempt_id']):
                        raise ContractError('attempt_unresolved', 'attempt_id', existing['attempt_id'])
                    if attempt_seq is None:
                        proof = u.conn.execute("SELECT 1 FROM events WHERE stream=? AND (type='request_not_sent' OR (type='submit_failed' AND json_extract(body,'$.class')='pre_acceptance'))", ('attempt:' + existing['attempt_id'],)).fetchone()
                        if not proof:
                            raise ContractError('pre_acceptance_evidence_required', 'attempt_id', existing['attempt_id'])
                    body = json.loads(u.conn.execute(
                        "SELECT body FROM attempts WHERE id=?",
                        (existing["attempt_id"],)).fetchone()[0] or "{}")
                    rid = body.get("reservation_id")
                    if rid and attempt_seq is not None:
                        try:
                            self.budget.release(
                                rid, evidence="pre-acceptance failure; "
                                "no remote_id so no provider charge")
                        except ContractError:
                            pass
                    u.conn.execute(
                        "DELETE FROM remote_holds WHERE attempt_id=?",
                        (existing["attempt_id"],))
                    u.conn.execute(
                        "DELETE FROM effect_bindings WHERE attempt_id=?",
                        (existing["attempt_id"],))
                else:
                    return existing["attempt_id"]
            if u.conn.execute("SELECT 1 FROM meta WHERE key IN ('restore_pending','spend_overrun')").fetchone():
                raise ContractError("dispatch_blocked", "reconciliation")
            if attempt_seq is None:
                attempt_seq = u.conn.execute('SELECT COALESCE(MAX(attempt_seq),0)+1 FROM attempts WHERE job_id=?', (job_id,)).fetchone()[0]
            price = self._price(spec)
            rid = None
            if spec["kind"] in PAID:
                self.budget.authorize_or_raise(auth, auth.scope_hash, spec["provider"], spec["model"], wire_hash(spec["request"]), price, now=self.clock())
                applicable = self._budgets(auth, spec, price)
                # A zero quote still needs an auditable settlement; an
                # unexpected nonzero charge must become an overrun, not vanish.
                rid = self.budget.reserve(
                    f"effect:{authority_id}:{operation_key}:{attempt_seq}",
                    [(bid, price.reserve_amount) for bid in applicable], auth.id)
            capacity = REMOTE_CAPACITY.get(spec["provider"]) if spec["kind"] == "generation" else None
            if capacity:
                from ..scheduler.scheduler import CAPACITIES
                count = u.conn.execute("SELECT count(*) FROM remote_holds WHERE capacity=?", (capacity,)).fetchone()[0]
                configured = u.conn.execute("SELECT limit_n FROM capacities WHERE name=?", (capacity,)).fetchone()
                limit = configured["limit_n"] if configured else CAPACITIES[capacity]
                if count >= limit:
                    raise ContractError("capacity_full", "capacity", capacity)
            aid = self.executor.prepare(job_id, attempt_seq, spec["request"],
                kind=spec["kind"], reservation_id=rid, provider=spec["provider"],
                model=spec["model"], billing_scope=spec["account"],
                extra={"authorization_id": auth.id, "operation_key": operation_key})
            u.conn.execute("INSERT INTO effect_bindings VALUES(?,?,?,?,?,?)",
                (aid, auth.id, operation_key, spec.get("price_id"), worker_id, fencing))
            if capacity:
                u.conn.execute("INSERT INTO remote_holds VALUES(?,?,?,?)", (aid, job_id, capacity, utcnow()))
            return aid

    def _budgets(self, auth, spec, price):
        ids = set(auth.binding["budget_ids"])
        retired={r[0][len('retired:budget:'):] for r in self.db.conn.execute("SELECT key FROM meta WHERE key LIKE 'retired:budget:%'")}
        if ids & retired:raise ContractError('restored_budget_retired','budget_ids')
        applicable = []
        for row in self.db.conn.execute("SELECT * FROM budgets WHERE unit=?", (price.unit,)):
            if row["id"] in retired:continue
            match = (row["id"] in ids or row["scope"] == "aggregate" or
                     (row["scope"] == "provider" and row["scope_key"] == spec["provider"]) or
                     (row["scope"] == "category" and row["scope_key"] == spec["kind"]))
            if match:
                applicable.append(row["id"])
        # A grant's ceiling is necessary but not a replacement for funded scope.
        if not any(bid in ids and not bid.startswith("authority:") for bid in applicable):
            raise ContractError("budget_required", "unit", price.unit)
        return applicable

    def _price(self, spec):
        if not spec.get("price_id"):
            return None
        row = self.db.uow().records.get("priceassessment", spec["price_id"])
        if row is None or row["status"] in {"stale", "revoked"}:
            raise ContractError("no_price_assessment", "price_id")
        return PriceAssessment(**json.loads(row["body"]))

    def _lease(self, job_id, fencing, worker_id):
        job = self.db.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["status"] not in {"reserved", "dispatching", "running"} or job["lease_owner"] != worker_id or job["fencing_token"] != fencing or not job["lease_expires"] or job["lease_expires"] <= utcnow():
            raise ContractError("stale_fencing", "job_id", job_id)
        paused = self.db.conn.execute("SELECT 1 FROM scheduler_flags WHERE key IN ('paused','draining',?) AND value='1'", (f"paused:{job['experiment_id']}",)).fetchone()
        if paused:
            raise ContractError("dispatch_paused", "experiment_id", job["experiment_id"])

    def preflight(self, attempt_id):
        row = self.db.conn.execute("SELECT * FROM effect_bindings WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise ContractError("authority_required", "attempt_id", attempt_id)
        auth = self._scope(row["authorization_id"])
        spec = auth.binding["operations"][row["operation_key"]]
        attempt = self.db.conn.execute("SELECT *, json_extract(body,'$.reservation_id') AS reservation_id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        self._lease(attempt["job_id"], row["fencing"], row["worker_id"])
        if attempt["request_hash"] != wire_hash(spec["request"]):
            raise ContractError("request_scope_mismatch", "attempt_id", attempt_id)
        if spec["kind"] in PAID:
            price = self._price(spec)
            self.budget.authorize_or_raise(auth, auth.scope_hash, spec["provider"], spec["model"], attempt["request_hash"], price, now=self.clock())
            if price.reserve_amount:
                held = self.db.conn.execute("SELECT status,authorization_id FROM reservations WHERE id=?", (attempt["reservation_id"],)).fetchone()
                if held is None or held["status"] != "held" or held["authorization_id"] != auth.id:
                    raise ContractError("reservation_required", "attempt_id", attempt_id)
        return spec

    def settle(self, attempt_id, actual, kind, evidence):
        if not evidence:
            raise ContractError("settlement_needs_evidence", "evidence")
        attempt = self.db.conn.execute("SELECT *, json_extract(body,'$.reservation_id') AS reservation_id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if not attempt or not attempt["reservation_id"]:
            raise ContractError("reservation_required", "attempt_id", attempt_id)
        lines = self.db.conn.execute("SELECT budget_id FROM reservation_lines WHERE reservation_id=?", (attempt["reservation_id"],)).fetchall()
        self.budget.settle(attempt["reservation_id"], kind, {r["budget_id"]: actual for r in lines}, evidence)

    def cancel_prepared(self, attempt_id, evidence):
        """Only a never-dispatched attempt can release without a provider receipt."""
        if not evidence:
            raise ContractError("resolution_needs_evidence", "evidence")
        with self.db.uow() as u:
            row = u.conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row or row["status"] != "prepared":
                raise ContractError("attempt_unresolved", "attempt_id", attempt_id)
            reservation_id = json.loads(row["body"]).get("reservation_id")
            if reservation_id:
                self.budget.release(reservation_id, evidence=evidence)
            u.conn.execute("UPDATE attempts SET status='cancelled' WHERE id=? AND status='prepared'", (attempt_id,))
            u.conn.execute("DELETE FROM remote_holds WHERE attempt_id=?", (attempt_id,))
            u.conn.execute("UPDATE outbox SET status='cancelled' WHERE json_extract(body,'$.attempt_id')=?", (attempt_id,))
            u.events.append(f"attempt:{attempt_id}", "prepared_cancelled", {"evidence": evidence})
