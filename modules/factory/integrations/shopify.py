"""Read-only Shopify Admin GraphQL adapter (F11 checklist 1–2).

- Injectable transport: `transport(query, variables) -> (status, json)`.
  It never sees credentials; the caller wires an authenticated transport.
- Mutations are refused before dispatch — this adapter is read-only.
- API version pinned at 2026-04 (verified with the pilot store).
- Pagination helpers distinguish a completed inventory from a truncated
  page: `complete` is only true when hasNextPage was observed False.
"""
import re
from urllib.parse import urlsplit

from ..domain.errors import ContractError
from ..seeds.ssrf import assert_fetchable
from ..testing.fakes import ProviderError

API_VERSION = "2026-04"
MUTATION_RE = re.compile(r"\bmutation\b", re.I)


class ShopifyAdmin:
    def __init__(self, transport, resolver=None):
        self._transport = transport
        self._resolver = resolver

    def graphql(self, query, variables=None):
        if MUTATION_RE.search(query):
            raise ContractError("writes_forbidden", "query",
                                "adapter is read-only")
        status, payload = self._transport(query, variables or {})
        if status in (401, 403):
            raise ProviderError("missing_scope", http_status=status)
        if not 200 <= status < 300:
            raise ProviderError("shopify_http_error", http_status=status)
        if not isinstance(payload, dict):
            raise ProviderError("shopify_invalid_payload")
        if payload.get("errors"):
            kinds = " ".join(
                e.get("extensions", {}).get("code", "")
                for e in payload["errors"] if isinstance(e, dict))
            if "ACCESS_DENIED" in kinds:
                raise ProviderError("missing_scope", http_status=403)
            raise ProviderError("shopify_graphql_errors")
        return payload.get("data", {})

    # ------------------------------------------------- catalog reads

    def products_page(self, cursor=None, page_size=10):
        """→ {"products": [...], "hasNextPage": bool, "endCursor": str}.
        Concrete query lives in the transport's implementation of the
        paginated shape; adapters return already-normalized rows."""
        raise NotImplementedError

    def media_page(self, product_id, cursor=None, page_size=10):
        raise NotImplementedError

    def product_by_handle(self, handle):
        raise NotImplementedError

    def refresh_media_url(self, media_id):
        raise NotImplementedError

    def media_download(self, url):
        """Bounded, validated fetch of a CDN URL → (bytes, content_type)."""
        assert_fetchable(url, resolver=self._resolver)
        status, headers, raw = self._transport_fetch(url)
        if status in (403, 410):
            raise ProviderError("expired_source", http_status=status)
        if status == 404:
            raise ProviderError("media_unavailable", http_status=404)
        if not 200 <= status < 300:
            raise ProviderError("media_http_error", http_status=status)
        return raw, (headers or {}).get("content-type", "")

    def _transport_fetch(self, url):
        raise NotImplementedError


def storefront_product_ref(url):
    """Parse a storefront product URL → handle (+ variant id if given)."""
    from urllib.parse import parse_qs
    try:
        p = urlsplit(url)
    except ValueError:
        raise ContractError("unsupported_url", "url", "unparseable")
    m = re.fullmatch(r"/products/([a-z0-9][a-z0-9-]*)", p.path or "")
    if not m:
        raise ContractError("unsupported_url", "url",
                            "expected /products/<handle>")
    variant = parse_qs(p.query).get("variant", [None])[0]
    return {"handle": m.group(1), "variant": variant}


PRODUCTS_QUERY = """
query($cursor: String, $pageSize: Int!) {
  products(first: $pageSize, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title status descriptionHtml
      variants(first: 100) { nodes {
        id title availableForSale
        price { amount currencyCode } } }
      media(first: $pageSize) {
        pageInfo { hasNextPage endCursor }
        nodes { id mediaContentType
          ... on MediaImage { image { url } }
          ... on Video { sources { url mimeType } } } }
    } } }
"""

MEDIA_PAGE_QUERY = """
query($id: ID!, $cursor: String, $pageSize: Int!) {
  product(id: $id) {
    media(first: $pageSize, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { id mediaContentType
        ... on MediaImage { image { url } }
        ... on Video { sources { url mimeType } } } } } }
"""

BY_HANDLE_QUERY = """
query($handle: String!) {
  productByHandle(handle: $handle) {
    id handle title status descriptionHtml
    variants(first: 100) { nodes {
      id title availableForSale price { amount currencyCode } } }
    media(first: 100) { nodes { id mediaContentType
      ... on MediaImage { image { url } }
      ... on Video { sources { url mimeType } } } } } }
"""


def _norm_media(node):
    kind = {"MEDIA_IMAGE": "image", "VIDEO": "video"}.get(
        node.get("mediaContentType"), str(node.get("mediaContentType") or
                                        "unknown").lower())
    if kind == "image":
        url = ((node.get("image") or {}).get("url"))
    elif kind == "video":
        srcs = node.get("sources") or []
        url = srcs[0]["url"] if srcs else None
    else:
        url = None
    return {"id": node.get("id"), "type": kind, "url": url}


class LiveShopifyAdmin(ShopifyAdmin):
    """Real read-only Admin GraphQL calls through the injected transport.
    `transport(query, variables)` must already carry auth headers."""

    def products_page(self, cursor=None, page_size=10):
        data = self.graphql(PRODUCTS_QUERY,
                            {"cursor": cursor, "pageSize": page_size})
        conn = data.get("products") or {}
        nodes = conn.get("nodes") or []
        out = []
        for n in nodes:
            media = [(_norm_media(m), ) for m in
                     (n.get("media", {}).get("nodes") or [])]
            out.append({
                "id": n["id"], "handle": n["handle"], "title": n["title"],
                "status": n["status"],
                "descriptionHtml": n.get("descriptionHtml") or "",
                "variants": n.get("variants", {}).get("nodes") or [],
                "media": [m for (m,) in media],
                "media_has_next": bool(
                    n.get("media", {}).get("pageInfo", {})
                    .get("hasNextPage")),
                "media_cursor": n.get("media", {}).get("pageInfo", {})
                .get("endCursor")})
        pi = conn.get("pageInfo") or {}
        return {"products": out,
                "hasNextPage": bool(pi.get("hasNextPage")),
                "endCursor": pi.get("endCursor")}

    def media_page(self, product_id, cursor=None, page_size=10):
        data = self.graphql(MEDIA_PAGE_QUERY,
                            {"id": product_id, "cursor": cursor,
                             "pageSize": page_size})
        conn = (data.get("product") or {}).get("media") or {}
        pi = conn.get("pageInfo") or {}
        return {"media": [_norm_media(m)
                          for m in conn.get("nodes") or []],
                "hasNextPage": bool(pi.get("hasNextPage")),
                "endCursor": pi.get("endCursor")}

    def product_by_handle(self, handle):
        data = self.graphql(BY_HANDLE_QUERY, {"handle": handle})
        n = data.get("productByHandle")
        if n is None:
            raise ProviderError("product_not_found", http_status=404)
        return {"id": n["id"], "handle": n["handle"], "title": n["title"],
                "status": n["status"],
                "descriptionHtml": n.get("descriptionHtml") or "",
                "variants": n.get("variants", {}).get("nodes") or [],
                "media": [_norm_media(m)
                          for m in n.get("media", {}).get("nodes") or []],
                "media_has_next": False}

    def product_by_id(self, product_id):
        q = """query($id: ID!) { node(id: $id) { ... on Product {
          id handle title status descriptionHtml
          variants(first: 100) { nodes { id title availableForSale
            price { amount currencyCode } } }
          media(first: 100) { nodes { id mediaContentType
            ... on MediaImage { image { url } }
            ... on Video { sources { url mimeType } } } } } } }"""
        n = (self.graphql(q, {"id": product_id}).get("node") or {})
        if not n.get("id"):
            raise ProviderError("product_not_found", http_status=404)
        return {"id": n["id"], "handle": n["handle"], "title": n["title"],
                "status": n["status"],
                "descriptionHtml": n.get("descriptionHtml") or "",
                "variants": n.get("variants", {}).get("nodes") or [],
                "media": [_norm_media(m)
                          for m in n.get("media", {}).get("nodes") or []],
                "media_has_next": False}

    def refresh_media_url(self, media_id):
        q = """query($id: ID!) { node(id: $id) {
          ... on MediaImage { image { url } }
          ... on Video { sources { url } } } }"""
        node = (self.graphql(q, {"id": media_id}).get("node") or {})
        url = ((node.get("image") or {}).get("url")
               or (node.get("sources") or [{}])[0].get("url"))
        if not url:
            raise ProviderError("no_media_url")
        return url
