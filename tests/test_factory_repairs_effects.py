"""Execution safety at the real intent/executor and API action boundaries."""
import pytest
from modules.factory.domain.errors import ContractError
from modules.factory.execution import Executor
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeProvider
from modules.factory.testing.ids import IdFactory


def test_repeated_submission_and_restart_reuse_one_effect(tmp_path):
    db = Database(tmp_path / "db")
    provider = FakeProvider("fixture", tmp_path / "remote", IdFactory(tmp_path / "ids"), FakeClock())
    ex = Executor(db, provider)
    attempt = ex.prepare("job-one", 1, {"prompt": "p"})
    first = ex.submit(attempt)
    assert ex.submit(attempt)["operation_id"] == first["operation_id"]
    restarted = Executor(db, provider)
    assert restarted.prepare("job-one", 1, {"prompt": "p"}) == attempt
    assert restarted.submit(attempt)["operation_id"] == first["operation_id"]
    assert provider.effect_counts()["submit"] == 1


def test_effect_then_timeout_never_repeats_under_same_http_action(tmp_path):
    from modules.factory.api.idempotency import IdempotencyStore
    actions = IdempotencyStore(Database(tmp_path / "db"))
    effects = []
    def effect():
        effects.append("accepted")
        raise TimeoutError("lost receipt")
    with pytest.raises(TimeoutError):
        actions.run("one", "POST", "/effect", {}, effect)
    with pytest.raises(ContractError, match="idempotency_unresolved"):
        actions.run("one", "POST", "/effect", {}, effect)
    assert effects == ["accepted"]


def test_expired_worker_lease_does_not_free_unfinished_remote_slot(tmp_path):
    from modules.factory.scheduler import Scheduler
    from modules.factory.domain.records import Job
    db = Database(tmp_path / "db")
    sched = Scheduler(db, worker_id="worker-one")
    sched.submit_plan([Job(schema_version="job.v1", id=name, created_at="",
                          logical_key=name, phase="generate_vertex") for name in ("first", "second")])
    claimed = sched.claim()
    ex = Executor(db)
    aid = ex.prepare(claimed["id"], 1, {"prompt": "one"})
    ex.submit(aid, lambda: {"operation_id": "accepted-operation"})
    sched.complete(claimed["id"], claimed["fencing_token"])
    db.conn.execute("UPDATE capacity_holds SET expires_at='2000-01-01'")
    assert sched.claim() is None
    assert sched.status_snapshot()["capacities"]["vertex_submit"]["used"] == 1


def test_paid_generation_without_scoped_authority_never_calls_provider(tmp_path):
    db = Database(tmp_path / "db")
    ex = Executor(db)
    aid = ex.prepare("job", 1, {"prompt": "paid"}, kind="generation",
                     provider="jimeng_canvas")
    calls = []
    with pytest.raises(ContractError, match="authority_required"):
        ex.submit(aid, lambda: calls.append(1) or {"operation_id": "paid"})
    assert calls == []


def test_actual_charge_above_reservation_remains_visible_and_blocks_dispatch(tmp_path):
    from modules.factory.budget import BudgetService
    db = Database(tmp_path / "db")
    budget = BudgetService(db)
    budget.create_budget("usd", "usd_micros", "aggregate", cap=100)
    rid = budget.reserve("request", [("usd", 90)])
    budget.settle(rid, "invoice_confirmed", {"usd": 120}, evidence="receipt-120")
    assert budget.available("usd") == -20
    ex = Executor(db)
    aid = ex.prepare("later", 1, {})
    with pytest.raises(ContractError, match="dispatch_blocked"):
        ex.submit(aid, lambda: {"operation_id": "forbidden"})


def funded_stack(tmp_path, count=1, cap=100):
    from datetime import datetime, timedelta, timezone
    from modules.factory.budget import BudgetService
    from modules.factory.domain.records import Authorization, PriceAssessment, ProductionPlan, Job
    from modules.factory.execution.effects import EffectService, wire_hash
    from modules.factory.scheduler import Scheduler
    db = Database(tmp_path / "db")
    sched = Scheduler(db, worker_id="w")
    budget = BudgetService(db)
    budget.create_budget("credits", "jimeng_credits", "aggregate", cap=cap)
    plan = ProductionPlan(schema_version="production_plan.v1", id="p", created_at="2026-09-17T00:00:00Z", plan_hash="plan", experiment_id="e", experiment_revision=1, revision=1)
    with db.uow() as u:
        u.records.put(plan)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    auth = Authorization(schema_version="authorization.v1", id="auth:test", created_at="2026-09-17T00:00:00Z", status="authorized", scope_hash="plan", authorizing_action="operator:test", valid_until=expiry, allowed_providers=["jimeng_canvas"], allowed_models={"jimeng_canvas": ["fast"]}, caps={"jimeng_credits": cap})
    ops = []
    for i in range(count):
        req = {"prompt": str(i), "duration": 5}
        quote = PriceAssessment(schema_version="price_assessment.v1", id=f"q{i}", created_at="2026-09-17T00:00:00Z", kind="native_quote", plan_hash="plan", request_hash=wire_hash(req), provider="jimeng_canvas", model="fast", unit="jimeng_credits", amount=30, reserve_amount=30, rate_basis="fixture-catalog", valid_until=expiry)
        ops.append(dict(key=f"op{i}", kind="generation", provider="jimeng_canvas", model="fast", account="test-account", request=req, price=quote))
    ex = Executor(db)
    effects = EffectService(db, executor=ex)
    effects.approve(auth, "productionplan", "p", ops, ["credits"])
    sched.submit_plan([Job(schema_version="job.v1", id=f"j{i}", logical_key=f"j{i}", created_at="2026-09-17T00:00:00Z", experiment_id="e", phase="generate_jimeng") for i in range(count)])
    return db, sched, budget, ex, effects


def test_scoped_effect_is_atomic_idempotent_and_fenced(tmp_path):
    db, sched, budget, ex, effects = funded_stack(tmp_path)
    job = sched.claim()
    aid = effects.prepare("auth:test", "op0", job["id"], job["fencing_token"], "w")
    assert budget.available("credits") == 70
    calls = []
    assert ex.submit(aid, lambda: calls.append(1) or {"operation_id": "remote-1"})["operation_id"] == "remote-1"
    assert effects.prepare("auth:test", "op0", job["id"], job["fencing_token"], "w") == aid
    ex.submit(aid, lambda: calls.append(2))
    assert calls == [1]
    assert budget.available("credits") == 70
    effects.settle(aid, 30, "native_quote", "receipt")
    assert budget.available("credits") == 70


def test_stale_revision_and_worker_cannot_dispatch_prepared_effect(tmp_path):
    import json
    db, sched, budget, ex, effects = funded_stack(tmp_path)
    job = sched.claim()
    aid = effects.prepare("auth:test", "op0", job["id"], job["fencing_token"], "w")
    db.conn.execute("UPDATE jobs SET fencing_token=fencing_token+1 WHERE id=?", (job["id"],))
    with pytest.raises(ContractError, match="stale_fencing"):
        ex.submit(aid, lambda: {"operation_id": "forbidden"})
    row = db.uow().records.get("productionplan", "p")
    body = json.loads(row["body"])
    body["plan_hash"] = "edited"
    db.conn.execute("UPDATE records SET body=? WHERE kind='productionplan'", (json.dumps(body),))
    with pytest.raises(ContractError, match="stale_authorization"):
        ex.submit(aid, lambda: {"operation_id": "forbidden"})


def test_insufficient_budget_rolls_back_attempt_outbox_and_remote_hold(tmp_path):
    db, sched, budget, ex, effects = funded_stack(tmp_path, count=2, cap=50)
    first = sched.claim()
    effects.prepare("auth:test", "op0", first["id"], first["fencing_token"], "w")
    second = sched.claim()
    with pytest.raises(ContractError, match="reservation_blocked"):
        effects.prepare("auth:test", "op1", second["id"], second["fencing_token"], "w")
    assert db.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1
    assert db.conn.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    assert db.conn.execute("SELECT count(*) FROM remote_holds").fetchone()[0] == 1
    assert budget.available("credits") == 20


def test_five_remote_operations_remain_counted_after_local_completion(tmp_path):
    db, sched, budget, ex, effects = funded_stack(tmp_path, count=6, cap=300)
    for i in range(5):
        job = sched.claim()
        aid = effects.prepare("auth:test", f"op{i}", job["id"], job["fencing_token"], "w")
        ex.submit(aid, lambda: {"operation_id": f"remote-{i}"})
        sched.complete(job["id"], job["fencing_token"])
    db.conn.execute("UPDATE capacity_holds SET expires_at='2000-01-01'")
    assert sched.status_snapshot()["capacities"]["jimeng_submit"]["used"] == 5
    assert sched.claim() is None
    from types import SimpleNamespace
    ex.provider = SimpleNamespace(poll=lambda oid: {"status": "succeeded"})
    ex.poll("att:j0:1")
    assert sched.claim()["id"] == "j5"


def test_pause_only_one_experiment_and_collects_accepted_work(tmp_path):
    from modules.factory.domain.records import Job
    from modules.factory.scheduler import Scheduler
    db = Database(tmp_path / "db")
    sched = Scheduler(db, worker_id="w")
    sched.submit_plan([Job(schema_version="job.v1", id="paused-new", created_at="", logical_key="paused-new", experiment_id="e1", phase="generate_jimeng"),
                       Job(schema_version="job.v1", id="other-new", created_at="", logical_key="other-new", experiment_id="e2", phase="generate_jimeng"),
                       Job(schema_version="job.v1", id="collect-old", created_at="", logical_key="collect-old", experiment_id="e1", phase="collect")])
    sched.pause("e1")
    assert sched.claim()["id"] == "other-new"
    sched.pause()
    assert sched.claim() is None
    assert sched.claim("collect")["id"] == "collect-old"
