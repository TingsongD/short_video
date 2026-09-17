"""Explicit, offline operator approvals for contract fixtures.

Uses the same approval, budget, scheduler and effect commands as the application.
This module has no live transport and is never imported by application code.
"""
from datetime import datetime, timedelta, timezone

from ..budget import BudgetService
from ..domain.records import Authorization, Job, PriceAssessment, ProductionPlan, content_hash
from ..execution.effects import EffectService, wire_hash
from ..scheduler import Scheduler
from ..store.uow import utcnow


def approve_production(service, plan_id):
    plan = service.status(plan_id)["plan"]
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    budget = BudgetService(service.db)
    ids = []
    for unit, total in plan["total_price"].items():
        bid = f"fixture:{plan_id}:{unit}"
        budget.create_budget(bid, unit, "experiment", plan["experiment_id"], total)
        ids.append(bid)
    nodes = service._nodes(plan_id)
    models = {}
    for node in nodes.values():
        if node["kind"] == "picture":
            models.setdefault(node["provider"], set()).add(node["model"])
    auth = Authorization(schema_version="authorization.v1", id=f"auth:{plan_id}",
        created_at=utcnow(), status="authorized", scope_hash=plan["plan_hash"],
        caps=plan["total_price"], allowed_providers=list(models),
        allowed_models={p: sorted(m) for p,m in models.items()}, valid_until=expiry,
        authorizing_action="explicit offline fixture approval")
    return service.authorize(plan_id, auth, "offline-fixture-account", ids, expiry)


def approve_operation(db, executor, request, job_id, kind="tts", provider="elevenlabs", model="eleven_v3", unit="elevenlabs_credits", amount=1):
    key = content_hash([job_id, request])[:20]
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    plan = ProductionPlan(schema_version="production_plan.v1", id=f"plan:{key}",
        created_at=utcnow(), experiment_id="fixture-exp", experiment_revision=1,
        revision=1, plan_hash=content_hash(request))
    with db.uow() as u:
        u.records.put(plan)
    bid = f"budget:{key}"
    BudgetService(db).create_budget(bid, unit, "experiment", plan.experiment_id, amount)
    price = PriceAssessment(schema_version="price_assessment.v1", id=f"quote:{key}",
        created_at=utcnow(), kind="native_quote", plan_hash=plan.plan_hash,
        provider=provider, model=model, request_hash=wire_hash(request), unit=unit,
        amount=amount, reserve_amount=amount, rate_basis="offline-fixture", valid_until=expiry)
    auth = Authorization(schema_version="authorization.v1", id=f"auth:{key}",
        created_at=utcnow(), scope_hash=plan.plan_hash, status="authorized",
        allowed_providers=[provider], allowed_models={provider:[model]},
        caps={unit:amount}, valid_until=expiry, authorizing_action="explicit offline fixture approval", publication_authorized=kind == "publication")
    effects = EffectService(db, executor)
    effects.approve(auth, "productionplan", plan.id, [dict(key="operation",kind=kind,
        provider=provider, model=model, account="offline-fixture-account",request=request,price=price)], [bid])
    sched = Scheduler(db, worker_id=f"worker:{key}")
    sched.submit_plan([Job(schema_version="job.v1",id=job_id,created_at=utcnow(),logical_key=job_id,phase="external",experiment_id=plan.experiment_id)])
    job = sched.claim()
    if job is None or job["id"] != job_id:
        raise RuntimeError("fixture operation has other queued work")
    return effects.prepare(auth.id, "operation", job_id, job["fencing_token"], sched.worker_id)


class FixtureEffects:
    """Test operator that approves one explicitly requested fake operation."""
    def __init__(self, db, executor):
        self.db, self.executor = db, executor

    def __call__(self, request, job_id, kind, provider, model):
        unique_job = f"{job_id}:{content_hash(request)[:12]}"
        previous = self.db.conn.execute("SELECT id FROM attempts WHERE job_id=?", (unique_job,)).fetchone()
        if previous:
            return previous["id"]
        unit = "viral_outliers_credits" if kind == "research" else "usd_micros"
        if provider not in {"viral_outliers", "analysis", "drive", "upload_post"}:
            provider = "analysis"
        return approve_operation(self.db, self.executor, request, unique_job,
                                 kind=kind, provider=provider, model=model or "fixture", unit=unit)
