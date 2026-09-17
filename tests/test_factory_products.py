"""F11 — Shopify product and media snapshots."""
import json
from pathlib import Path

import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.errors import ContractError
from modules.factory.integrations.shopify import (
    LiveShopifyAdmin, storefront_product_ref)
from modules.factory.products import ProductImporter
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeShopify, ProviderError
from modules.factory.testing.fixtures import materialize
from modules.factory.testing.ids import IdFactory

CATALOG = json.loads(
    Path("tests/factory_fixtures/shopify-catalog/catalog.json").read_text())
SHOP = CATALOG["shop"]

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082")


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "artifacts", db=db)
    media_dir = tmp_path / "cdn"
    media_dir.mkdir()
    for m in ("sky-jeans-front.png", "sky-jeans-side.png",
              "tank-front.png", "midi-rose.png", "hoodie.png"):
        (media_dir / m).write_bytes(_TINY_PNG)
    ws = tmp_path / "ws"
    materialize("core-30s", ws)
    import shutil
    shutil.copy(ws / "fixtures" / "core-30s" / "source.mp4",
                media_dir / "midi-rose-spin.mp4")
    src = FakeShopify("shopify", tmp_path / "remote",
                      IdFactory(tmp_path / "ids.json"), FakeClock(),
                      catalog=CATALOG, media_dir=media_dir)
    imp = ProductImporter(db, arts, src, SHOP)
    return {"db": db, "arts": arts, "src": src, "imp": imp}


class TestImport:
    def test_paginated_catalog_complete(self, env):
        out = env["imp"].import_catalog()
        exp = CATALOG["expectations"]
        assert out["products_seen"] == exp["product_count"]
        assert out["inventory_complete"] is True
        assert len(out["snapshots"]) == 4
        # each snapshot has all media artifacts accounted for
        for sid in out["snapshots"]:
            snap = env["imp"].get(sid)
            product = next(p for pg in CATALOG["pages"]
                           for p in pg["products"]
                           if p["id"] == snap.product_id)
            assert len(snap.media_artifact_ids) == len(product["media"])

    def test_media_kinds_and_coverage(self, env):
        out = env["imp"].import_catalog()
        midi = env["imp"].get(next(
            s for s in out["snapshots"]
            if env["imp"].get(s).title == "Rose-Stripe Midi Dress"))
        assert midi.media_coverage == {"images": 1, "videos": 1}
        tank = env["imp"].get(next(
            s for s in out["snapshots"]
            if env["imp"].get(s).title == "Image-Only Tank"))
        assert tank.media_coverage["videos"] == 0
        assert any("no_video_reference" in w for w in tank.warnings)
        assert any("single_view_only" in w for w in tank.warnings)

    def test_expiring_media_refreshed(self, env):
        env["imp"].import_catalog()
        # the expiring URL went through the approved refresh path
        assert env["src"].state.doc["refreshed"]

    def test_removed_permission_blocks_refresh_not_snapshot(self, env):
        out = env["imp"].import_catalog()
        env["src"].remove_permission("gid://shopify/MediaImage/70001")
        with pytest.raises(ProviderError):
            env["src"].media_download(
                "https://cdn.fixture/sky-jeans-front.png")
        # existing snapshot stays usable
        snap = env["imp"].get(out["snapshots"][0])
        assert snap.media_artifact_ids

    def test_unavailable_variants_flagged(self, env):
        env["imp"].import_catalog()
        snap = env["imp"].snapshot_product(
            env["src"].product_by_id("gid://shopify/Product/8001"),
            variant_id="gid://shopify/ProductVariant/90002")
        sel = env["imp"].select([(snap.id, None)])
        assert any("unavailable_variant" in w for w in sel["warnings"])
        # and the hoodie only has an unavailable variant
        hood = env["imp"].snapshot_product(
            env["src"].product_by_id("gid://shopify/Product/8004"))
        assert hood.available is False

    def test_duplicate_products_deduped(self, env):
        out = env["imp"].import_catalog()
        sel = env["imp"].select([(out["snapshots"][0], None),
                                 (out["snapshots"][0], None)])
        assert len(sel["items"]) == 1
        assert any("duplicate_product" in w for w in sel["warnings"])


class TestClaims:
    def test_factual_claims_only(self, env):
        out = env["imp"].import_catalog()
        snap = env["imp"].get(out["snapshots"][0])
        kinds = {c["kind"] for c in snap.claims}
        assert "price" in kinds and "availability" in kinds
        basis = next(c for c in snap.claims
                     if c["kind"] == "selection_basis")
        assert basis["text"] == "manual_selection"
        assert basis["popularity_evidence"] is None

    def test_rich_text_sanitized(self, env):
        out = env["imp"].import_catalog()
        snap = env["imp"].get(out["snapshots"][0])
        desc = next(c for c in snap.claims
                    if c["kind"] == "description_text")
        assert "<" not in desc["text"] and "dot" in desc["text"]

    def test_missing_angle_is_explicit(self, env):
        out = env["imp"].import_catalog()
        tank = next(s for s in out["snapshots"]
                    if env["imp"].get(s).title == "Image-Only Tank")
        gap = env["imp"].reference_gap(tank, needed="back")
        assert gap["covered"] is False
        assert "insufficient_views" in gap["reason"]


class TestRefreshAndFreeze:
    def test_refresh_creates_new_revision(self, env):
        out = env["imp"].import_catalog()
        sid = out["snapshots"][0]
        v0 = env["imp"].get(sid)
        # price change upstream → re-import → new revision
        cat = json.loads(json.dumps(CATALOG))
        cat["pages"][0]["products"][0]["variants"][0][
            "price"]["amount"] = "45.00"
        src2 = FakeShopify("shopify2", env["db"].path and Path(
            env["db"].path).parent / "remote",
            IdFactory(Path(env["db"].path).parent / "ids2.json"),
            FakeClock(), catalog=cat,
            media_dir=env["src"].media_dir)
        imp2 = ProductImporter(env["db"], env["arts"], src2, SHOP)
        imp2.import_catalog()
        revs = env["db"].conn.execute(
            "SELECT revision FROM records WHERE id=? ORDER BY revision",
            (sid,)).fetchall()
        assert [r["revision"] for r in revs] == [0, 1]
        # old revision still readable — running plan stays bound
        old = env["db"].conn.execute(
            "SELECT body FROM records WHERE id=? AND revision=0",
            (sid,)).fetchone()
        assert '"39' in old["body"] or "39000000" in old["body"]

    def test_identical_refresh_writes_nothing(self, env):
        env["imp"].import_catalog()
        env["imp"].import_catalog()
        n = env["db"].conn.execute(
            "SELECT COUNT(*) c FROM records WHERE kind='productsnapshot'"
        ).fetchone()["c"]
        assert n == 4                                   # one revision each


class TestTransportSafety:
    def test_mutation_refused(self):
        src = LiveShopifyAdmin(lambda q, v: (200, {"data": {}}))
        with pytest.raises(ContractError):
            src.graphql("mutation { productDelete(id: \"x\") { ok } }")

    def test_missing_scope_named(self):
        def transport(q, v):
            return 200, {"errors": [{"extensions":
                                     {"code": "ACCESS_DENIED"}}]}
        src = LiveShopifyAdmin(transport)
        with pytest.raises(ProviderError) as e:
            src.products_page()
        assert e.value.code == "missing_scope"

    def test_storefront_url_resolution(self, env):
        snap = env["imp"].resolve_storefront(
            "https://shop.example/products/sky-jeans?variant="
            "gid://shopify/ProductVariant/90002")
        assert snap.variant_id == "gid://shopify/ProductVariant/90002"
        assert snap.available is False        # the M/blue variant
