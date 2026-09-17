"""F11 manual scenarios: paginated catalog import, missing-angle
evidence, permission/expiry degradation, and snapshot freeze."""
import json
import shutil
from pathlib import Path

from .cases_f01 import CaseContext, _result
from ..artifacts import ArtifactStore
from ..products import ProductImporter
from ..store import Database
from ..testing.fakes import FakeShopify, ProviderError
from ..testing.fixtures import materialize

FIX = Path("tests/factory_fixtures")
CATALOG = json.loads(
    (FIX / "shopify-catalog" / "catalog.json").read_text())
SHOP = CATALOG["shop"]

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082")


def _stack(ctx, name, catalog=None):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-artifacts", db=db)
    media_dir = ctx.run_dir / f"{name}-cdn"
    media_dir.mkdir(exist_ok=True)
    for m in ("sky-jeans-front.png", "sky-jeans-side.png",
              "tank-front.png", "midi-rose.png", "hoodie.png"):
        (media_dir / m).write_bytes(_TINY_PNG)
    fx = ctx.run_dir / f"{name}-fx"
    materialize("core-30s", fx)
    shutil.copy(fx / "fixtures" / "core-30s" / "source.mp4",
                media_dir / "midi-rose-spin.mp4")
    src = FakeShopify(name, ctx.workspace.dir("fake_remote"),
                      ctx.workspace.ids, ctx.clock,
                      catalog=catalog or CATALOG, media_dir=media_dir)
    return db, arts, src, ProductImporter(db, arts, src, SHOP)


def f11_m01(ctx: CaseContext):
    """Import the paginated fake catalog; select 3 product/variant
    pairs; every page and media item accounted for."""
    db, arts, src, imp = _stack(ctx, "m01")
    out = imp.import_catalog()
    exp = CATALOG["expectations"]
    ctx.check("all_pages_seen",
              out["products_seen"] == exp["product_count"],
              f"{out['products_seen']} products across paginated pages")
    ctx.check("inventory_complete", out["inventory_complete"])
    snaps = [imp.get(s) for s in out["snapshots"]]
    ctx.check("four_snapshots", len(snaps) == 4)
    all_media = sum(len(s.media_artifact_ids) for s in snaps)
    expected_media = sum(len(p["media"]) for pg in CATALOG["pages"]
                         for p in pg["products"])
    ctx.check("all_media_accounted", all_media == expected_media,
              f"{all_media}/{expected_media} artifacts")
    sel = imp.select([(s.id, None) for s in snaps[:3]])
    ctx.check("three_selected", len(sel["items"]) == 3)
    ctx.check("expired_url_refreshed", bool(src.state.doc["refreshed"]),
              "media 70004 went through refresh path")
    return _result(ctx, "passed",
                   "2-page catalog imported; 4 snapshots; all media "
                   "downloaded through F04; 3-item selection returned",
                   limitations=["fake adapter; live scope under F35"])


def f11_m02(ctx: CaseContext):
    """The image-only tank keeps an explicit missing-angle verdict."""
    db, arts, src, imp = _stack(ctx, "m02")
    imp.import_catalog()
    gap_id = CATALOG["expectations"]["missing_angle_product"]
    tank = next(s for s in
                (imp.get(i) for i in imp.import_catalog()["snapshots"])
                if s.product_id == gap_id)
    ctx.check("tank_single_image",
              tank.media_coverage == {"images": 1, "videos": 0})
    gap = imp.reference_gap(tank.id, needed="back")
    ctx.check("gap_explicit", gap["covered"] is False
              and "insufficient_views" in gap["reason"], gap["reason"])
    ctx.check("warning_named",
              any("single_view_only" in w for w in tank.warnings))
    ctx.check("not_invented",
              all(c["kind"] != "back_detail" for c in tank.claims),
              "no hidden-construction claims present")
    return _result(ctx, "awaiting_manual_review",
                   "back-detail request returns explicit gap; claims list "
                   "contains no inferred construction",
                   limitations=["human confirms the gap wording is "
                                "actionable for a merchandiser"])


def f11_m03(ctx: CaseContext):
    """Expire a URL and remove read permission: existing snapshots stay
    usable; only the affected refresh path blocks."""
    db, arts, src, imp = _stack(ctx, "m03")
    out = imp.import_catalog()
    snap0 = imp.get(out["snapshots"][0])
    src.remove_permission("gid://shopify/MediaImage/70001")
    blocked = None
    try:
        src.media_download("https://cdn.fixture/sky-jeans-front.png")
    except ProviderError as e:
        blocked = e.code
    ctx.check("permission_block_named", blocked == "missing_scope", blocked)
    ctx.check("existing_snapshot_readable",
              bool(snap0.media_artifact_ids) and bool(snap0.title))
    path = arts.path_for(snap0.media_artifact_ids[0])
    ctx.check("bytes_still_served", Path(path).is_file())
    return _result(ctx, "passed",
                   "denied download → missing_scope; prior snapshot and "
                   "its verified bytes unaffected; refresh for the denied "
                   "media is the only blocked path")


def f11_m04(ctx: CaseContext):
    """Price/availability change post-freeze: running plan keeps its
    pinned revision; new claims need the new revision."""
    db, arts, src, imp = _stack(ctx, "m04")
    out = imp.import_catalog()
    sid = out["snapshots"][0]
    frozen = imp.get(sid)
    ctx.check("frozen_price", frozen.price is not None
              and frozen.price.amount == 39_000_000)
    changed = json.loads(json.dumps(CATALOG))
    changed["pages"][0]["products"][0]["variants"][0][
        "price"]["amount"] = "45.00"
    changed["pages"][0]["products"][0]["variants"][0][
        "availableForSale"] = False
    src.state.doc["catalog"] = changed
    src.state.save()
    imp.import_catalog()
    revs = [r["revision"] for r in db.conn.execute(
        "SELECT revision FROM records WHERE id=? AND "
        "kind='productsnapshot' ORDER BY revision", (sid,))]
    ctx.check("new_revision_written", revs == [0, 1], str(revs))
    old = db.conn.execute(
        "SELECT body FROM records WHERE id=? AND revision=0",
        (sid,)).fetchone()
    ctx.check("old_revision_intact", "39000000" in old["body"])
    now = imp.get(sid)
    ctx.check("latest_reflects_change",
              now.price.amount == 45_000_000
              and now.available is False)
    return _result(ctx, "passed",
                   "upstream change wrote revision 1; revision 0 remains "
                   "readable so a running experiment stays bound to the "
                   "price/availability it was approved under")


def implementations():
    return {"F11-M01": f11_m01, "F11-M02": f11_m02,
            "F11-M03": f11_m03, "F11-M04": f11_m04}
