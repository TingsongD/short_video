"""F05 manual scenarios: concurrent reservations, nested USD caps,
ambiguous holds, authorization binding."""
import threading

from .cases_f01 import CaseContext, _result
from ..budget import BudgetService, ReservationBlocked
from ..domain import Authorization, PriceAssessment
from ..store import Database
from ..testing.fakes import FakeProvider, ProviderError

NOW = "2026-09-16T12:00:00Z"


def _svc(ctx, name):
    db = Database(ctx.workspace.dir("store") / f"{name}.db")
    return BudgetService(db)


def _auth(**kw):
    a = Authorization(schema_version="authorization.v1", id="au:qa",
                      created_at=NOW, status="authorized",
                      scope_hash="plan-v1",
                      allowed_providers=["jimeng_canvas", "google_vertex"],
                      allowed_models={"jimeng_canvas": ["canvas-m"],
                                      "google_vertex": ["omni"]},
                      caps={"jimeng_credits": 100, "usd_micros": 1000000},
                      valid_until="2027-01-01T00:00:00Z")
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def _price(**kw):
    p = PriceAssessment(schema_version="price_assessment.v1", id="pa:qa",
                        created_at=NOW, kind="native_quote",
                        request_hash="rh-1", provider="jimeng_canvas",
                        unit="jimeng_credits", amount=10, reserve_amount=10,
                        valid_until="2027-01-01T00:00:00Z")
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def f05_m01(ctx: CaseContext):
    svc = _svc(ctx, "m05-1")
    svc.create_budget("b:credits", "jimeng_credits", "category",
                      "generation", cap=100)
    p = ctx.provider("f05m01", unit="jimeng_credits")
    results = {}
    barrier = threading.Barrier(2)

    def worker(job, amount):
        own = BudgetService(Database(svc.db.path))
        try:
            barrier.wait()
            rid = own.reserve(f"rh-{job}", [("b:credits", amount)])
            # Reserved work dispatches; blocked work never submits.
            op = p.submit({"job": job},
                          price={"unit": "jimeng_credits",
                                 "amount": amount})
            results[job] = ("reserved", rid, op["operation_id"])
        except ReservationBlocked as e:
            results[job] = ("blocked", e.reason)
        finally:
            own.db.close()

    ts = [threading.Thread(target=worker, args=(j, a))
          for j, a in (("a", 60), ("b", 50))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    statuses = sorted(v[0] for v in results.values())
    ctx.check("exactly_one_reserves", statuses == ["blocked", "reserved"],
              str(results))
    ctx.check("one_submission_only", p.effect_counts()["submit"] == 1)
    ctx.check("cap_respected",
              svc.available("b:credits") in (40, 50))
    svc.db.close()
    return _result(ctx, "passed",
                   "concurrent 60+50 on a 100 cap: one reserved and "
                   "submitted, one blocked with zero submissions")


def f05_m02(ctx: CaseContext):
    svc = _svc(ctx, "m05-2")
    svc.create_budget("b:agg", "usd_micros", "aggregate", cap=1_000_000)
    svc.create_budget("b:vertex", "usd_micros", "provider",
                      "google_vertex", cap=800_000)
    svc.create_budget("b:credits", "jimeng_credits", "category",
                      "generation", cap=10_000)
    svc.reserve("rh-prior", [("b:agg", 300_000)])      # $0.30 elsewhere
    try:
        svc.reserve("rh-v", [("b:vertex", 750_000), ("b:agg", 750_000)])
        ctx.check("aggregate_blocks", False)
    except ReservationBlocked as e:
        ctx.check("aggregate_blocks", e.budget_id == "b:agg",
                  f"{e.budget_id}: {e.reason}")
    # Jimeng credits cannot pay a USD cost — separate unit rows.
    ctx.check("credits_not_usd", svc.available("b:credits") == 10_000
              and svc.available("b:agg") == 700_000)
    svc.db.close()
    return _result(ctx, "passed",
                   "$0.75 Vertex request blocked by $1 aggregate (0.30 "
                   "committed) despite fitting the $0.80 sublimit; credits "
                   "never substitute for USD")


def f05_m03(ctx: CaseContext):
    svc = _svc(ctx, "m05-3")
    svc.create_budget("b", "jimeng_credits", "category", "gen", cap=100)
    p = ctx.provider("f05m03", unit="jimeng_credits")
    rid = svc.reserve("rh-lost", [("b", 60)])
    try:
        p.submit({"x": 1}, faults=("accept-then-timeout",),
                 price={"unit": "jimeng_credits", "amount": 60})
    except ProviderError as e:
        ctx.check("ack_lost", e.code == "response_lost")
    svc.mark_ambiguous(rid)
    # Restart: new service over the same DB; hold must still count.
    svc2 = BudgetService(Database(svc.db.path))
    ctx.check("hold_survives_restart", svc2.available("b") == 40)
    try:
        svc2.reserve("rh-2", [("b", 60)])
        ctx.check("no_phantom_headroom", False)
    except ReservationBlocked:
        ctx.check("no_phantom_headroom", True)
    svc.db.close(); svc2.db.close()
    return _result(ctx, "awaiting_manual_review",
                   "ambiguous acceptance keeps the 60-credit hold across "
                   "restart; a competing 60 cannot conjure headroom",
                   limitations=["human inspects hold ledger entries"])


def f05_m04(ctx: CaseContext):
    svc = _svc(ctx, "m05-4")
    svc.create_budget("b", "jimeng_credits", "category", "gen", cap=100)
    auth = _auth()
    # Plan changed after approval → hash mismatch blocks.
    reasons = svc.check_authorization(
        auth, plan_hash="plan-v2-edited", provider="jimeng_canvas",
        model="canvas-m", request_hash="rh-1", price=_price())
    ctx.check("changed_plan_blocked", "plan_hash_mismatch" in reasons)
    # Expired quote blocks.
    reasons = svc.check_authorization(
        auth, plan_hash="plan-v1", provider="jimeng_canvas",
        model="canvas-m", request_hash="rh-1",
        price=_price(valid_until="2020-01-01T00:00:00Z"))
    ctx.check("expired_quote_blocked", "quote_expired" in reasons)
    # Exact authorized revision proceeds.
    reasons = svc.check_authorization(
        auth, plan_hash="plan-v1", provider="jimeng_canvas",
        model="canvas-m", request_hash="rh-1", price=_price())
    ctx.check("exact_revision_passes", reasons == [])
    svc.db.close()
    return _result(ctx, "passed",
                   "edited plan and stale quote each block; only the exact "
                   "authorized revision + fresh quote proceed")


def implementations():
    return {"F05-M01": f05_m01, "F05-M02": f05_m02,
            "F05-M03": f05_m03, "F05-M04": f05_m04}
