"""Product snapshots (F11): authorized shop + product refs → immutable
snapshots with variant/media coverage, verified reference artifacts and
factual claims only.

- Snapshots are immutable revisions: a catalog refresh writes a new
  revision; a running experiment keeps its pinned (id, revision).
- pagination_complete is only claimed when every page was observed —
  a truncated inventory stays visibly partial.
- Popularity is never invented: without an authorized sales metric the
  claim list carries "manual_selection" instead of "best seller".
"""
import hashlib
import json
import re
from decimal import Decimal
from html.parser import HTMLParser

from ..domain.errors import ContractError
from ..domain.money import Money
from ..domain.records import ProductSnapshot
from ..integrations.shopify import storefront_product_ref
from ..store.uow import utcnow
from ..testing.fakes import ProviderError


def snapshot_id_for(shop, product_id):
    digest = hashlib.sha256(f"{shop}|{product_id}".encode()).hexdigest()[:12]
    return f"psnap-{digest}"


class _Text(HTMLParser):
    """descriptionHtml → plain text; source HTML retained separately."""
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html):
    p = _Text()
    p.feed(html or "")
    return re.sub(r"\s+", " ", "".join(p.parts)).strip()


def _money(price):
    if not price:
        return None
    micros = int(Decimal(str(price["amount"])) * 1_000_000)
    return Money("usd_micros", micros)


class ProductImporter:
    def __init__(self, db, artifacts, adapter, shop):
        self.db = db
        self.artifacts = artifacts
        self.adapter = adapter
        self.shop = shop

    # ---------------------------------------------------------- import

    def import_catalog(self, selection=None, observed_at=None):
        """Paginate the catalog; snapshot each selected product (all when
        selection is None). Returns snapshot ids + warnings."""
        products, cursor, complete = [], None, True
        while True:
            page = self.adapter.products_page(cursor)
            products.extend(page["products"])
            if not page["hasNextPage"]:
                break
            cursor = page["endCursor"]
        wanted = set(selection) if selection else None
        snaps, warnings = [], []
        for p in products:
            if wanted and p["id"] not in wanted and \
                    p.get("handle") not in wanted:
                continue
            snap = self.snapshot_product(p, observed_at=observed_at)
            snaps.append(snap.id)
            warnings.extend(snap.warnings)
        return {"snapshots": snaps, "warnings": warnings,
                "inventory_complete": complete,
                "products_seen": len(products)}

    def snapshot_product(self, product, variant_id=None, observed_at=None):
        """Build an immutable snapshot for one product row (as returned
        by products_page or product_by_handle)."""
        media = list(product.get("media", []))
        # Follow nested media pagination before claiming completeness.
        while product.get("media_has_next"):
            page = self.adapter.media_page(product["id"],
                                           product.get("media_cursor"))
            media.extend(page["media"])
            product = dict(product, media_has_next=page["hasNextPage"],
                           media_cursor=page["endCursor"])
        observed = observed_at or utcnow()
        artifacts, coverage = [], {"images": 0, "videos": 0}
        warnings = []
        for m in media:
            aid = self._ingest_media(m, product["id"])
            if aid:
                artifacts.append(aid)
                coverage["videos" if m["type"] == "video"
                         else "images"] += 1
        if coverage["videos"] == 0:
            warnings.append(f"{product['id']}: no_video_reference")
        if coverage["images"] <= 1 and coverage["videos"] == 0:
            warnings.append(f"{product['id']}: single_view_only")
        variant = self._variant(product, variant_id)
        claims = self._claims(product, variant)
        sid = snapshot_id_for(self.shop, product["id"])
        prior = self.db.uow().records.get("productsnapshot", sid)
        snap = ProductSnapshot(
            schema_version="product_snapshot.v1", id=sid,
            created_at=observed,
            revision=(prior["revision"] + 1) if prior else 0,
            shop=self.shop, product_id=product["id"],
            variant_id=(variant or {}).get("id", ""),
            title=product.get("title", ""),
            options={"variant_title": (variant or {}).get("title", "")},
            price=_money((variant or {}).get("price")),
            available=(variant or {}).get("availableForSale"),
            media_artifact_ids=artifacts, claims=claims,
            observed_at=observed, pagination_complete=True,
            media_coverage=coverage, warnings=warnings)
        body = snap.to_dict()
        body["price"] = snap.price.to_dict() if snap.price else None
        # revision identity is the observed facts — not the wall-clock
        # fields, which would make every refresh look like a change
        fact_body = {k: v for k, v in body.items()
                     if k not in ("observed_at", "created_at",
                                  "revision", "content_hash")}
        digest = hashlib.sha256(json.dumps(
            fact_body, sort_keys=True, default=str).encode()).hexdigest()
        if prior and prior["content_hash"] == digest:
            return snap                        # refresh, no change
        snap.content_hash = digest
        snap.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(snap)
            u.events.append(f"product:{sid}", "snapshot",
                            {"revision": snap.revision,
                             "coverage": coverage,
                             "warnings": warnings})
        return snap

    # ---------------------------------------------------------- media

    def _ingest_media(self, media, product_id):
        """Download + F04 intake. Expired URLs go through the adapter's
        refresh path once; missing scope surfaces as a named blocker."""
        url = media.get("url")
        if not url:
            return None
        try:
            data, _ = self.adapter.media_download(url)
        except ProviderError as e:
            if e.code != "expired_source":
                raise
            fresh = self.adapter.refresh_media_url(media["id"])
            data, _ = self.adapter.media_download(fresh)
        kind = "video" if media["type"] == "video" else "image"
        artifact = self.artifacts.intake_bytes(
            data, provenance="shopify",
            source_key=media["id"],
            source_detail=f"product:{product_id} url:{url[:60]}",
            requested_kind=kind)
        return artifact.id

    # --------------------------------------------------------- helpers

    def _variant(self, product, variant_id):
        variants = product.get("variants", [])
        if variant_id:
            for v in variants:
                if v["id"] == variant_id or v["id"].endswith(variant_id):
                    return v
            raise ContractError("unknown_variant", "variant_id",
                                variant_id)
        return variants[0] if variants else None

    def _claims(self, product, variant):
        """Factual claims only — what the snapshot actually observed."""
        claims = [{"kind": "title", "text": product.get("title", "")},
                  {"kind": "description_text",
                   "text": html_to_text(product.get("descriptionHtml"))}]
        if variant:
            claims.append({"kind": "variant",
                           "text": variant.get("title", "")})
            price = _money(variant.get("price"))
            if price:
                claims.append({"kind": "price",
                               "text": f"{variant['price']['currencyCode']} "
                                       f"{variant['price']['amount']}",
                               "money": price.to_dict()})
            claims.append({"kind": "availability",
                           "text": "available" if variant.get(
                               "availableForSale") else "unavailable"})
        # Popularity: only with an authorized sales metric. Absent one,
        # the claim is an explicit merchandising choice, not "best seller".
        claims.append({"kind": "selection_basis",
                       "text": "manual_selection",
                       "popularity_evidence": None})
        return claims

    # ----------------------------------------------------- selection

    def get(self, snapshot_id):
        row = self.db.uow().records.get("productsnapshot", snapshot_id)
        if row is None:
            raise ContractError("unknown_snapshot", "id", snapshot_id)
        snap = ProductSnapshot(**json.loads(row["body"]))
        if isinstance(snap.price, dict):
            snap.price = Money.from_dict(snap.price)
        return snap

    def resolve_storefront(self, url):
        ref = storefront_product_ref(url)
        product = self.adapter.product_by_handle(ref["handle"])
        return self.snapshot_product(product, variant_id=ref["variant"])

    def select(self, selections):
        """selections: [(snapshot_id, variant_id|None)]. Dedupe by
        product; warn on unavailable variants; never invents demand."""
        items, warnings, seen = [], [], set()
        for sid, variant_id in selections:
            snap = self.get(sid)
            if variant_id and variant_id != snap.variant_id:
                product = self.adapter.product_by_id(snap.product_id)
                snap = self.snapshot_product(product,
                                             variant_id=variant_id)
                sid = snap.id
            if snap.product_id in seen:
                warnings.append(f"duplicate_product:{snap.product_id}")
                continue
            seen.add(snap.product_id)
            if snap.available is False:
                warnings.append(f"unavailable_variant:{snap.variant_id}")
            items.append({"snapshot_id": sid, "product_id": snap.product_id,
                          "variant_id": snap.variant_id})
        return {"items": items, "warnings": warnings}

    def reference_gap(self, snapshot_id, needed="back"):
        """Whether the snapshot's actual coverage shows `needed` view.
        A single image is not proof of a garment's back."""
        snap = self.get(snapshot_id)
        cov = snap.media_coverage
        if cov.get("videos", 0) > 0:
            return {"covered": True, "via": "video"}
        if cov.get("images", 0) <= 1:
            return {"covered": False, "reason":
                    f"insufficient_views: {cov.get('images', 0)} image(s), "
                    "no video — request another asset or revise the shot"}
        return {"covered": None, "reason":
                "multiple images; angle coverage needs human review"}
