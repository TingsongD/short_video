"""F14 — experiment, control and treatment planning."""
import pytest

from modules.factory.domain.clocks import FPS_30, FrameInterval
from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import (
    Beat, FormatTemplate, ProductSnapshot, ReferenceBlueprint, Slot)
from modules.factory.experiments import ExperimentService
from modules.factory.store import Database


def _blueprint():
    spans = [(0, 120), (120, 240), (240, 360), (360, 510),
             (510, 780), (780, 900)]
    roles = ["hook", "product_reveal", "product_reveal",
             "product_reveal", "proof", "cta"]
    beats = [Beat(id=f"b{i}", role=r, target=FrameInterval(s, e))
             for i, (r, (s, e)) in enumerate(zip(roles, spans))]
    return ReferenceBlueprint(
        schema_version="blueprint.v1", id="bp-1", seed_id="seed-x",
        created_at="2026-09-16T00:00:00Z", revision=1, status="accepted",
        clock=FPS_30, target_frames=900, beats=beats,
        content_hash="bphash")


def _template():
    return FormatTemplate(
        schema_version="format_template.v1", id="ft-haul",
        created_at="2026-09-16T00:00:00Z", revision=1,
        status="candidate", derived_from_blueprint="bphash",
        slots=[Slot(id=f"s{i}", kind=k, frames=f)
               for i, (k, f) in enumerate(zip(
                   ("hook", "product", "product", "product",
                    "proof", "cta"),
                   (120, 120, 120, 150, 270, 120)))])


def _snap(pid="gid://shopify/Product/8001", price="39.00"):
    return ProductSnapshot(
        schema_version="product_snapshot.v1", id="psnap-x",
        created_at="2026-09-16T00:00:00Z", revision=0,
        shop="fixture-shop", product_id=pid,
        variant_id="gid://shopify/ProductVariant/90001",
        title="Sky-Blue Polka-Dot Jeans", price=None, available=True,
        claims=[{"kind": "title", "text": "Sky-Blue Polka-Dot Jeans"},
                {"kind": "price", "text": "USD 39.00"},
                {"kind": "availability", "text": "available"}],
        observed_at="2026-09-16T00:00:00Z")


def _segments():
    spans = [(0, 120), (120, 240), (240, 360), (360, 510),
             (510, 780), (780, 900)]
    roles = ["hook", "product", "product", "product", "proof", "cta"]
    copies = ["POV: your Monday needs these jeans",
              "Sky-Blue Polka-Dot Jeans, USD 39.00",
              "The knit that goes desk to dinner",
              "The dress people ask about",
              "Every piece under sixty dollars",
              "Links below — sizes go fast"]
    return [{"id": f"seg{i}", "slot_id": f"s{i}", "role": r,
             "target": {"start_frame": s, "end_frame": e},
             "copy": c, "speech": f"vo-{i}", "captions": f"cap-{i}",
             "picture": f"pic-{i}", "transition": "cut",
             "claims": (["Sky-Blue Polka-Dot Jeans", "USD 39.00"]
                        if i == 1 else [])}
            for i, (r, (s, e), c) in enumerate(
                zip(roles, spans, copies))]


@pytest.fixture
def svc(tmp_path):
    db = Database(tmp_path / "f.db")
    es = ExperimentService(db)
    out = es.create("exp1", "seed-x", _blueprint(), _template(),
                    [_snap()], _segments())
    return {"db": db, "es": es, "control": out["control"],
            "a": out["variant_a"]}


class TestControl:
    def test_frozen_fields(self, svc):
        c = svc["control"]
        pkg = c.packaging
        assert pkg["target_frames"] == 900
        assert pkg["template_ref"] == {"id": "ft-haul", "revision": 1}
        assert pkg["products"][0]["snapshot_id"] == "psnap-x"
        assert c.blueprint_hash == "bphash"
        assert svc["a"].variant_key == "A"


class TestBranching:
    def test_b_hook_declared(self, svc):
        es = svc["es"]
        def edit(body):
            body["segments"][0]["copy"] = "Stop scrolling — one outfit."
            body["segments"][0]["speech"] = "vo-new"
            body["segments"][0]["captions"] = "cap-new"
            body["segments"][0]["picture"] = "pic-new"
            return body
        v = es.branch("exp1", "B", "hook",
                      [FrameInterval(0, 120)], edit,
                      hypothesis="pattern interrupt beats POV",
                      primary_metric="3s_hold",
                      allowed_fields=["copy", "speech", "captions",
                                      "picture"])
        assert v.variant_key == "B"
        rep = es.review("exp1", "B")
        assert rep["problems"] == []

    def test_undeclared_music_rejected(self, svc):
        es = svc["es"]
        def edit(body):
            body["music"] = {"role": "different_track"}
            body["segments"][0]["copy"] = "x"
            return body
        with pytest.raises(ContractError) as e:
            es.branch("exp1", "B", "hook", [FrameInterval(0, 120)], edit,
                      hypothesis="h", primary_metric="m",
                      allowed_fields=["copy"])
        assert "locked_field_changed" in e.value.detail

    def test_undeclared_product_rejected(self, svc):
        es = svc["es"]
        def edit(body):
            body["products"] = [{"snapshot_id": "psnap-other"}]
            return body
        with pytest.raises(ContractError) as e:
            es.branch("exp1", "C", "body",
                      [FrameInterval(360, 510)], edit,
                      hypothesis="h", primary_metric="m",
                      allowed_fields=["copy"])
        assert "locked_field_changed" in e.value.detail

    def test_change_outside_region_rejected(self, svc):
        es = svc["es"]
        def edit(body):
            body["segments"][4]["copy"] = "edit proof, declare hook"
            return body
        with pytest.raises(ContractError) as e:
            es.branch("exp1", "B", "hook", [FrameInterval(0, 120)], edit,
                      hypothesis="h", primary_metric="m",
                      allowed_fields=["copy"])
        assert "change_outside_region" in e.value.detail

    def test_copy_change_needs_speech_dep(self, svc):
        es = svc["es"]
        def edit(body):
            body["segments"][0]["copy"] = "new hook"
            body["segments"][0]["speech"] = "vo-new"
            body["segments"][0]["captions"] = "cap-new"
            body["segments"][0]["picture"] = "pic-new"
            return body
        with pytest.raises(ContractError) as e:
            # copy allowed but speech/captions/picture not declared
            es.branch("exp1", "B", "hook", [FrameInterval(0, 120)], edit,
                      hypothesis="h", primary_metric="m",
                      allowed_fields=["copy"])
        assert "dependency_outside_region" in e.value.detail

    def test_four_branches_share_parent(self, svc):
        es = svc["es"]
        fields = ["copy", "speech", "captions", "picture"]
        for key, region in (("B", FrameInterval(0, 120)),
                            ("C", FrameInterval(360, 510)),
                            ("D", FrameInterval(780, 900))):
            def edit(body, region=region):
                for s in body["segments"]:
                    iv = FrameInterval(s["target"]["start_frame"],
                                       s["target"]["end_frame"])
                    if iv.overlaps(region):
                        for f in fields:
                            s[f] = f"{s[f]}-{key}"
                return body
            v = es.branch("exp1", key, {"B": "hook", "C": "body",
                                        "D": "ending"}[key],
                          [region], edit, hypothesis=f"{key} hyp",
                          primary_metric="retention",
                          allowed_fields=fields)
            assert v.experiment_revision == \
                svc["control"].revision == 1
        # zero additional undeclared treatments — A only has 4 keys total
        import json as _j
        rows = svc["db"].conn.execute(
            "SELECT id FROM records WHERE kind='variantplan'").fetchall()
        assert {r["id"] for r in rows} == \
            {"exp1:a", "exp1:b", "exp1:c", "exp1:d"}


class TestAcceptance:
    def test_supported_claims_pass(self, svc):
        rep = svc["es"].acceptance_report(
            "exp1", _blueprint(), _template(), [_snap()])
        assert rep["problems"] == []

    def test_unsupported_claim_flagged(self, tmp_path):
        db = Database(tmp_path / "f.db")
        es = ExperimentService(db)
        segs = _segments()
        segs[0]["claims"] = ["best seller in the store"]   # invented
        es.create("exp1", "seed-x", _blueprint(), _template(),
                  [_snap()], segs)
        rep = es.acceptance_report("exp1", _blueprint(),
                                   _template(), [_snap()])
        assert any(p["flag"] == "unsupported_claim"
                   for p in rep["problems"])

    def test_accept_freeze_and_hash_gate(self, svc):
        es = svc["es"]
        with pytest.raises(ContractError) as e:
            es.accept("exp1", "wronghash")
        assert e.value.code == "revision_mismatch"
        acc = es.accept("exp1", svc["control"].content_hash)
        assert acc.status == "accepted"


class TestPostFreeze:
    def test_revise_control_stales_variants_and_prices(self, svc):
        es = svc["es"]
        fields = ["copy", "speech", "captions", "picture"]
        def edit(body):
            body["segments"][0]["copy"] = "x"
            body["segments"][0]["speech"] = "x"
            body["segments"][0]["captions"] = "x"
            body["segments"][0]["picture"] = "x"
            return body
        es.branch("exp1", "B", "hook", [FrameInterval(0, 120)], edit,
                  hypothesis="h", primary_metric="m",
                  allowed_fields=fields)
        es.accept("exp1", svc["control"].content_hash)
        # a price assessment bound to the old plan hash
        from modules.factory.domain.records import PriceAssessment
        with svc["db"].uow() as u:
            pa = PriceAssessment(
                schema_version="price_assessment.v1", id="pa-1",
                created_at="2026-09-16T00:00:00Z",
                kind="native_quote", request_hash="req-1",
                unit="usd_micros", amount=1,
                plan_hash=svc["control"].content_hash)
            u.records.put(pa)
        out = es.revise_control(
            "exp1",
            lambda b: {**b, "packaging":
                       {**b["packaging"], "voice": {"id": "v2"}}},
            reason="voice fix")
        assert out["revision"].revision == 2
        assert "exp1:b" in out["staled"]
        import json as _j
        row = svc["db"].conn.execute(
            "SELECT body FROM records WHERE id='pa-1'").fetchone()
        assert _j.loads(row["body"])["status"] == "stale"
        # execution waits for the new acceptance — old hash no longer valid
        with pytest.raises(ContractError):
            es.accept("exp1", svc["control"].content_hash)
