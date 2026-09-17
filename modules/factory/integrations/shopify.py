"""Read-only Shopify Admin GraphQL adapter (F11 checklist 1–2).

- Injectable transport: `transport(query, variables) -> (status, json)`.
  It never sees credentials; the caller wires an authenticated transport.
- Mutations are refused before dispatch — this adapter is read-only.
- API version pinned at 2026-04 (verified with the pilot store).
- Pagination helpers distinguish a completed inventory from a truncated
  page: `complete` is only true when hasNextPage was observed False.
"""
import re
from urllib.parse import urlsplit, urljoin

from ..domain.errors import ContractError
from ..seeds.ssrf import assert_fetchable, check_redirect, MAX_BYTES, MAX_REDIRECTS
from ..testing.fakes import ProviderError

API_VERSION = "2026-04"
MUTATION_RE = re.compile(r"\bmutation\b", re.I)


class ShopifyAdmin:
    def __init__(self, transport, resolver=None, media_transport=None, max_bytes=MAX_BYTES):
        self._transport = transport
        self._resolver = resolver
        self._media_transport = media_transport
        self._max_bytes = max_bytes

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
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            assert_fetchable(current, resolver=self._resolver) if hop == 0 else check_redirect(current, hop, resolver=self._resolver)
            status, headers, raw = self._transport_fetch(current)
            headers = {k.lower(): v for k, v in (headers or {}).items()}
            if status in (301, 302, 303, 307, 308):
                if not headers.get("location"):
                    raise ProviderError("redirect_missing_location")
                current = urljoin(current, headers["location"])
                continue
            if status in (403, 410):
                raise ProviderError("expired_source", http_status=status)
            if status == 404:
                raise ProviderError("media_unavailable", http_status=404)
            if not 200 <= status < 300:
                raise ProviderError("media_http_error", http_status=status)
            if not isinstance(raw, bytes) or len(raw) > self._max_bytes:
                raise ProviderError("oversize_payload")
            return raw, headers.get("content-type", "")
        raise ProviderError("redirect_limit")

    def _transport_fetch(self, url):
        if self._media_transport is None:
            raise ProviderError("media_transport_not_configured")
        return self._media_transport("GET", url, None)


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
  shop { currencyCode }
  products(first: $pageSize, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title status descriptionHtml
      variants(first: 100) { pageInfo { hasNextPage endCursor } nodes {
        id title availableForSale
        price } }
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
  shop { currencyCode }
  productByHandle(handle: $handle) {
    id handle title status descriptionHtml
    variants(first: 100) { pageInfo { hasNextPage endCursor } nodes {
      id title availableForSale price } }
    media(first: 100) { pageInfo { hasNextPage endCursor } nodes { id mediaContentType
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

    def _variants(self, product, currency):
        conn = product.get("variants") or {}
        items, seen = list(conn.get("nodes") or []), set()
        while (conn.get("pageInfo") or {}).get("hasNextPage"):
            cursor = conn["pageInfo"].get("endCursor")
            if not cursor or cursor in seen:
                raise ProviderError("shopify_pagination_incomplete")
            seen.add(cursor)
            data = self.graphql(VARIANTS_QUERY, {"id": product["id"], "cursor": cursor})
            conn = (data.get("product") or {}).get("variants")
            if not conn or "pageInfo" not in conn:
                raise ProviderError("shopify_pagination_incomplete")
            items.extend(conn.get("nodes") or [])
        return [{**item, "price": {"amount": item["price"], "currencyCode": currency}}
                for item in items]

    def _normalize(self, product, currency):
        media = product.get("media") or {}
        if "pageInfo" not in media or "pageInfo" not in (product.get("variants") or {}):
            raise ProviderError("shopify_pagination_incomplete")
        return {"id": product["id"], "handle": product["handle"], "title": product["title"],
            "status": product["status"], "descriptionHtml": product.get("descriptionHtml") or "",
            "variants": self._variants(product, currency),
            "media": [_norm_media(m) for m in media.get("nodes") or []],
            "media_has_next": media["pageInfo"]["hasNextPage"], "media_cursor": media["pageInfo"].get("endCursor")}

    def products_page(self, cursor=None, page_size=10):
        data = self.graphql(PRODUCTS_QUERY, {"cursor": cursor, "pageSize": page_size})
        conn = data.get("products") or {}
        if "pageInfo" not in conn:
            raise ProviderError("shopify_pagination_incomplete")
        return {"products": [self._normalize(n, data["shop"]["currencyCode"]) for n in conn.get("nodes") or []],
            **conn["pageInfo"]}

    def media_page(self, product_id, cursor=None, page_size=10):
        data = self.graphql(MEDIA_PAGE_QUERY, {"id": product_id, "cursor": cursor, "pageSize": page_size})
        conn = (data.get("product") or {}).get("media") or {}
        if "pageInfo" not in conn:
            raise ProviderError("shopify_pagination_incomplete")
        return {"media": [_norm_media(m) for m in conn.get("nodes") or []], **conn["pageInfo"]}

    def product_by_handle(self, handle):
        data = self.graphql(BY_HANDLE_QUERY, {"handle": handle})
        if not data.get("productByHandle"):
            raise ProviderError("product_not_found", http_status=404)
        return self._normalize(data["productByHandle"], data["shop"]["currencyCode"])

    def product_by_id(self, product_id):
        query = BY_HANDLE_QUERY.replace('$handle: String!', '$id: ID!').replace('productByHandle(handle: $handle)', 'product(id: $id)')
        data = self.graphql(query, {"id": product_id})
        if not data.get("product"):
            raise ProviderError("product_not_found", http_status=404)
        return self._normalize(data["product"], data["shop"]["currencyCode"])

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

VARIANTS_QUERY = """
query($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { id title availableForSale price }
    }
  }
}
"""


def configured_shopify(shop, credentials, policy):
    """Read-only production wiring; credentials are resolved at each call."""
    import json
    from .http import BoundedHTTP
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", shop):
        raise ContractError("invalid_shop_domain", "shop")
    graphql_http = BoundedHTTP("shopify", policy, max_bytes=8 * 1024 * 1024)
    media_http = BoundedHTTP("shopify", policy)
    def graphql(query, variables):
        status, _, raw = graphql_http("POST", f"https://{shop}/admin/api/{API_VERSION}/graphql.json",
            json.dumps({"query": query, "variables": variables}).encode(),
            {"X-Shopify-Access-Token": credentials()["SHOPIFY_ADMIN_ACCESS_TOKEN"], "Content-Type": "application/json"})
        return status, json.loads(raw)
    return LiveShopifyAdmin(graphql, media_transport=media_http)
