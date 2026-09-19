"""F05 — prices, budgets, approvals, reservations. Offline; uses the
money-boundaries fixture."""
import json
import threading

import pytest

from modules.factory.budget import (AuthorizationRejected, BudgetService,
                                    ReservationBlocked)
from modules.factory.domain import (Authorization, ContractError,
                                    PriceAssessment)
from modules.factory.store import Database
from modules.factory.testing import fixtures

NOW = "2026-09-16T12:00:00Z"
BOUNDARIES = json.loads((fixtures.FIXTURE_ROOT
                         / "money-boundaries" / "budgets.json").read_text())


@pytest.fixture
def svc(tmp_path):
    db = Database(tmp_path / "f.db")
    from datetime import datetime
    svc = BudgetService(db, clock=lambda: datetime.fromisoformat(NOW.replace("Z", "+00:00")))
    svc.db_path = tmp_path / "f.db"      # for per-thread connections
    yield svc
    db.close()


def _auth(**kw):
    a = Authorization(schema_version="authorization.v1", id="au:1",
                      created_at=NOW, status="authorized",
                      scope_hash="planhash1",
                      allowed_providers=["jimeng_canvas", "google_vertex"],
                      allowed_models={"jimeng_canvas": ["m1"],
                                      "google_vertex": ["omni"]},
                      caps={"jimeng_credits": 100, "usd_micros": 1000000},
                      valid_until="2027-01-01T00:00:00Z")
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def _price(unit="usd_micros", reserve=750000, request_hash="rh1", **kw):
    p = PriceAssessment(schema_version="price_assessment.v1", id="pa:1",
                        created_at=NOW, kind="usage_estimate",
                        request_hash=request_hash, provider="google_vertex",
                        unit=unit, amount=reserve, reserve_amount=reserve,
                        valid_until="2027-01-01T00:00:00Z")
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class TestReservationRace:
    def test_credit_scenario_one_wins(self, svc):
        sc = BOUNDARIES["credit_scenario"]
        svc.create_budget("b:credits", "jimeng_credits", "category",
                          "generation", cap=sc["cap_credits"])
        results = {}
        barrier = threading.Barrier(2)

        def worker(job, amount):
            own = BudgetService(Database(svc.db_path))   # own connection
            try:
                barrier.wait()
                rid = own.reserve(f"rh-{job}", [("b:credits", amount)])
                results[job] = ("reserved", rid)
            except ReservationBlocked as e:
                results[job] = ("blocked", e.reason)
            finally:
                own.db.close()

        threads = [threading.Thread(target=worker,
                                    args=(c["job"], c["amount"]))
                   for c in sc["competing"]]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        statuses = sorted(v[0] for v in results.values())
        assert statuses == ["blocked", "reserved"]   # exactly one wins
        committed = sc["cap_credits"] - svc.available("b:credits")
        winner = next(c for c in sc["competing"]
                      if results[c["job"]][0] == "reserved")
        assert committed == winner["amount"] <= sc["cap_credits"]

    def test_same_request_hash_replays_same_reservation(self, svc):
        svc.create_budget("b", "jimeng_credits", "category", "g", cap=100)
        r1 = svc.reserve("rh-dup", [("b", 60)])
        r2 = svc.reserve("rh-dup", [("b", 60)])
        assert r1 == r2
        assert svc.available("b") == 40


class TestUsdCaps:
    def test_same_id_can_raise_but_not_change_or_lower_ceiling(self, svc):
        svc.create_budget("b:agg", "usd_micros", "aggregate", cap=100)
        svc.reserve("r-existing", [("b:agg", 100)])

        assert svc.create_budget("b:agg", "usd_micros", "aggregate",
                                 cap=350) == "b:agg"
        assert svc.available("b:agg") == 250

        with pytest.raises(ContractError, match="budget_ceiling_decrease"):
            svc.create_budget("b:agg", "usd_micros", "aggregate", cap=349)
        with pytest.raises(ContractError, match="budget_identity_conflict"):
            svc.create_budget("b:agg", "usd_micros", "provider",
                              "google_vertex", cap=400)

    def test_aggregate_blocks_despite_sublimit(self, svc):
        sc = BOUNDARIES["usd_scenario"]
        svc.create_budget("b:agg", "usd_micros", "aggregate",
                          cap=sc["aggregate_cap_micros"])
        svc.create_budget("b:vertex", "usd_micros", "provider",
                          "google_vertex",
                          cap=sc["vertex_sublimit_micros"])
        # $0.30 already committed by another route
        svc.reserve("rh-existing",
                    [("b:agg", sc["existing_other_usage_micros"])])
        # $0.75 Vertex: fits the 0.80 sublimit but blows the aggregate.
        with pytest.raises(ReservationBlocked) as e:
            svc.reserve("rh-vertex",
                        [("b:vertex", sc["request"]["amount_micros"]),
                         ("b:agg", sc["request"]["amount_micros"])])
        assert e.value.budget_id == "b:agg"
        # And the credit balance is never interchangeable with USD.
        svc.create_budget("b:credits", "jimeng_credits", "category", "g",
                          cap=10_000)
        with pytest.raises(ReservationBlocked):
            svc.reserve("rh-vertex2", [("b:agg", 900000)])

    def test_zero_and_unset_caps(self, svc):
        svc.create_budget("b:zero", "usd_micros", "aggregate", cap=0)
        svc.create_budget("b:unset", "usd_micros", "aggregate")
        with pytest.raises(ReservationBlocked) as e:
            svc.reserve("r1", [("b:zero", 1)])
        assert e.value.reason == "cap_zero"
        with pytest.raises(ReservationBlocked) as e:
            svc.reserve("r2", [("b:unset", 1)])
        assert e.value.reason == "cap_unset"

    def test_exact_boundary(self, svc):
        svc.create_budget("b", "usd_micros", "aggregate", cap=100)
        svc.reserve("r-committed", [("b", 40)])
        svc.reserve("r-exact", [("b", 60)])
        assert svc.available("b") == 0
        with pytest.raises(ReservationBlocked):
            svc.reserve("r-over", [("b", 1)])


class TestAmbiguousAndSettlement:
    def test_ambiguous_hold_survives_restart(self, svc, tmp_path):
        svc.create_budget("b", "usd_micros", "aggregate", cap=1000)
        rid = svc.reserve("rh-lost", [("b", 400)])
        svc.mark_ambiguous(rid)
        # "Restart": new service object on the same DB.
        svc2 = BudgetService(Database(tmp_path / "f.db"))
        assert svc2.available("b") == 600
        with pytest.raises(ReservationBlocked):
            svc2.reserve("rh-new", [("b", 700)])
        svc2.db.close()

    def test_settle_and_release(self, svc):
        svc.create_budget("b", "usd_micros", "aggregate", cap=1000)
        rid = svc.reserve("rh1", [("b", 400)])
        svc.settle(rid, "invoice_confirmed", {"b": 380},
                   evidence="receipt:1")
        assert svc.available("b") == 620          # settled actual, not reserve
        svc.settle(rid, "invoice_confirmed", {"b": 380})   # idempotent
        rid2 = svc.reserve("rh2", [("b", 100)])
        svc.release(rid2, evidence="provider: failed before accept")
        assert svc.available("b") == 620          # only settled 380 counts
        with pytest.raises(ContractError):
            svc.release(rid2)

    def test_over_reserved_charge_is_recorded(self, svc):
        svc.create_budget("b", "usd_micros", "aggregate", cap=1000)
        rid = svc.reserve("rh1", [("b", 900)])
        svc.settle(rid, "invoice_confirmed", {"b": 1200}, evidence="receipt")
        assert svc.available("b") == -200
        with pytest.raises(ContractError, match="dispatch_blocked"):
            svc.reserve("new", [("b", 1)])

    def test_settlement_upgrades_to_invoice_without_conflict(self, svc):
        """A usage_estimate hold settled first can later be corrected to
        the invoice-confirmed charge — the original estimate stays in the
        ledger as the adjustment's prior state."""
        svc.create_budget("b", "usd_micros", "aggregate", cap=1000)
        rid = svc.reserve("rh1", [("b", 400)])
        svc.settle(rid, "usage_estimate", {"b": 400}, evidence="estimate")
        svc.adjust_settlement(rid, "invoice_confirmed", {"b": 385},
                              evidence="invoice INV-1042",
                              operator="op-7")
        assert svc.available("b") == 615
        events = [json.loads(r[0]) for r in svc.db.conn.execute(
            "SELECT body FROM events WHERE type='settlement_adjusted'")]
        assert events[0]["prior"]["b"] == {"amount": 400,
                                          "kind": "usage_estimate"}
        assert events[0]["amounts"] == {"b": 385}
        # Never downgrade a confirmed charge back to an estimate.
        with pytest.raises(ContractError,
                           match="settlement_downgrade_refused"):
            svc.adjust_settlement(rid, "usage_estimate", {"b": 385},
                                  evidence="x", operator="op-7")
        # Idempotent replay — same kind and amounts is a no-op.
        svc.adjust_settlement(rid, "invoice_confirmed", {"b": 385},
                              evidence="invoice INV-1042",
                              operator="op-7")
        # A still-held reservation was never settled — nothing to adjust.
        rid2 = svc.reserve("rh2", [("b", 100)])
        with pytest.raises(ContractError, match="not_settled"):
            svc.adjust_settlement(rid2, "invoice_confirmed", {"b": 100},
                                  evidence="x", operator="op-7")
        # Missing operator/evidence is refused before touching the books.
        rid3 = svc.reserve("rh3", [("b", 10)])
        svc.settle(rid3, "usage_estimate", {"b": 10}, evidence="e")
        with pytest.raises(ContractError,
                           match="adjustment_needs_evidence"):
            svc.adjust_settlement(rid3, "invoice_confirmed", {"b": 10},
                                  evidence="", operator="op-7")

    def test_overrun_blocks_dispatch_until_operator_resolves(self, svc):
        svc.create_budget("b", "usd_micros", "aggregate", cap=1000)
        rid = svc.reserve("rh1", [("b", 900)])
        svc.settle(rid, "invoice_confirmed", {"b": 1200},
                   evidence="receipt")
        with pytest.raises(ContractError, match="dispatch_blocked"):
            svc.reserve("new", [("b", 1)])
        # Resolution needs operator + evidence + resolution detail.
        with pytest.raises(ContractError,
                           match="overrun_resolution_incomplete"):
            svc.resolve_overrun("op", "", "paid invoice")
        prior = svc.resolve_overrun(
            "op-7", "invoice INV-1042 reconciled",
            "overage confirmed real; ceiling raised to cover it")
        assert prior["budget"] == "b" and prior["actual"] == 1200
        # The overrun event is preserved; the block is lifted — but the
        # real overage still counts, so the declared remedy must be
        # applied before new spend fits.
        svc.create_budget("b", "usd_micros", "aggregate", cap=1300)
        svc.reserve("new", [("b", 1)])
        resolved = svc.db.conn.execute(
            "SELECT 1 FROM events WHERE type='spend_overrun_resolved'"
            ).fetchone()
        assert resolved
        with pytest.raises(ContractError, match="no_overrun_pending"):
            svc.resolve_overrun("op-7", "e", "r")


class TestAuthorization:
    def test_authorized_passes(self, svc):
        reasons = svc.check_authorization(
            _auth(), plan_hash="planhash1", provider="google_vertex",
            model="omni", request_hash="rh1", price=_price())
        assert reasons == []

    def test_wrong_plan_hash_blocks(self, svc):
        reasons = svc.check_authorization(
            _auth(), plan_hash="DIFFERENT", provider="google_vertex",
            model="omni", request_hash="rh1", price=_price())
        assert "plan_hash_mismatch" in reasons

    def test_expired_quote_and_provisional_block(self, svc):
        stale = _price(valid_until="2020-01-01T00:00:00Z")
        reasons = svc.check_authorization(
            _auth(), plan_hash="planhash1", provider="google_vertex",
            model="omni", request_hash="rh1", price=stale)
        assert "quote_expired" in reasons
        prov = _price(provisional=True)
        reasons = svc.check_authorization(
            _auth(), plan_hash="planhash1", provider="google_vertex",
            model="omni", request_hash="rh1", price=prov)
        assert "price_provisional" in reasons

    def test_model_and_unit_scoping(self, svc):
        reasons = svc.check_authorization(
            _auth(), plan_hash="planhash1", provider="google_vertex",
            model="veo-3", request_hash="rh1", price=_price())
        assert "model_not_authorized" in reasons
        reasons = svc.check_authorization(
            _auth(), plan_hash="planhash1", provider="jimeng_canvas",
            model="m1", request_hash="rh1",
            price=_price(unit="elevenlabs_credits"))
        assert any(r.startswith("no_cap_for_unit") for r in reasons)

    def test_revoked_and_no_authorization(self, svc):
        with pytest.raises(AuthorizationRejected):
            svc.authorize_or_raise(
                None, plan_hash="x", provider="p", model="m",
                request_hash="r", price=None)
        reasons = svc.check_authorization(
            _auth(status="revoked"), plan_hash="planhash1",
            provider="google_vertex", model="omni", request_hash="rh1",
            price=_price())
        assert "no_active_authorization" in reasons


class TestLegacyImport:
    def test_import_idempotent_and_readonly(self, svc, tmp_path):
        ledger = tmp_path / "ledger.json"
        ledger.write_text(json.dumps({"entries": [
            {"ts": "2026-01-01T00:00:00Z", "service": "vertex",
             "cost_usd": 0.41},
            {"ts": "2026-01-02T00:00:00Z", "service": "jimeng",
             "cost_usd": 0, "units": 30, "unit_type": "credits"}]}))
        r1 = svc.import_legacy_ledger(ledger)
        assert r1 == {"imported": 2, "skipped": 0}
        r2 = svc.import_legacy_ledger(ledger)
        assert r2 == {"imported": 0, "skipped": 2}
        # History is visible; it created no budget headroom.
        n = svc.db.conn.execute(
            "SELECT COUNT(*) FROM ledger_imports").fetchone()[0]
        assert n == 2
        assert svc.db.conn.execute(
            "SELECT COUNT(*) FROM budgets").fetchone()[0] == 0

    def test_spend_breakdown(self, svc):
        svc.create_budget("b1", "jimeng_credits", "category", "gen",
                          cap=100)
        svc.create_budget("b2", "usd_micros", "aggregate", cap=500)
        svc.reserve("rh1", [("b1", 40)])
        rid = svc.reserve("rh2", [("b2", 100)])
        svc.settle(rid, "invoice_confirmed", {"b2": 90})
        rows = {r["id"]: r for r in svc.spend_breakdown()}
        assert rows["b1"]["held"] == 40
        assert rows["b2"]["settled"] == 90
