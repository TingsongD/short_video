"""Viral Outliers source adapter (F09): metadata lookup and bounded
media download behind the shared provider protocol so the F07 executor
drives it (intent persisted before the effect, remote id saved on
ack, reconcile by identity).

The transport is injectable: `transport(method, url, body) ->
(status, headers, raw_bytes)`. It never sees credentials — the caller
supplies an authenticated transport if one is configured.

The YouTube download route may return a thumbnail instead of a video;
the adapter reports bytes + declared content-type verbatim and lets the
F04 probe/arbitrate path decide — it never labels an image a video.
"""
import json
from urllib.parse import urljoin, urlsplit

from ..events.redact import redact
from ..seeds.ssrf import (MAX_BYTES, MAX_REDIRECTS, assert_fetchable,
                          check_redirect)
from ..testing.fakes import ProviderError

BASE_URL = "https://viraloutliers.com"


class ViralOutliersSource:
    """Provider-protocol adapter over an injectable HTTP transport."""

    def __init__(self, transport, resolver=None, max_bytes=MAX_BYTES):
        self._transport = transport
        self._resolver = resolver
        self._max = max_bytes
        self._ops = {}          # op_id -> {status, request, result, blob}
        self._seq = 0

    # ------------------------------------------------------ provider api

    def submit(self, request):
        """request: {kind: 'metadata'|'media', post_id?, url?}."""
        self._seq += 1
        op_id = f"vo-src:{self._seq}"
        kind = request.get("kind")
        if kind == "metadata":
            result = self._metadata(request["post_id"])
            op = {"operation_id": op_id, "status": "succeeded",
                  "result": result}
        elif kind == "media":
            blob = self._fetch(request["url"])
            op = {"operation_id": op_id, "status": "accepted"}
            self._ops[op_id] = {"status": "succeeded", "blob": blob,
                                "request": request}
            return op
        else:
            raise ProviderError("unsupported_kind")
        self._ops[op_id] = {"status": "succeeded", "request": request,
                            "result": result}
        return op

    def poll(self, operation_id):
        op = self._ops.get(operation_id)
        if op is None:
            raise ProviderError("unknown_operation", http_status=404)
        return {"operation_id": operation_id, "status": op["status"],
                "result": op.get("result")}

    def download(self, operation_id, destination=None):
        op = self._ops.get(operation_id)
        if op is None:
            raise ProviderError("unknown_operation", http_status=404)
        blob = op.get("blob")
        if blob is None:
            raise ProviderError("no_payload", http_status=409)
        import hashlib
        data, content_type = blob
        if destination:
            with open(destination, "wb") as f:
                f.write(data)
        return {"sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "content_type": content_type,
                "path": destination}

    def reconcile(self, operation_id=None, request_hash=None):
        return self._ops.get(operation_id) if operation_id else None

    def cancel(self, operation_id):
        if operation_id in self._ops:
            self._ops[operation_id]["status"] = "cancelled"

    # -------------------------------------------------------- internals

    def _metadata(self, post_id):
        status, _, raw = self._transport(
            "GET", f"{BASE_URL}/api/v1/content/{post_id}", None)
        if status == 404:
            raise ProviderError("post_unavailable", http_status=404)
        if not 200 <= status < 300:
            raise ProviderError("metadata_http_error", http_status=status)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise ProviderError("metadata_unparseable")
        if not isinstance(payload, dict) or payload.get("error"):
            raise ProviderError("metadata_invalid")
        return payload

    def _fetch(self, url):
        """Bounded GET with per-hop SSRF validation. Redirects are
        followed manually so every hop is re-checked."""
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            if hop == 0:
                assert_fetchable(current, resolver=self._resolver)
            else:
                check_redirect(current, hop, resolver=self._resolver)
            status, headers, raw = self._transport("GET", current, None)
            if status in (301, 302, 303, 307, 308):
                loc = (headers or {}).get("location")
                if not loc:
                    raise ProviderError("redirect_missing_location")
                current = urljoin(current, loc)
                continue
            if status == 410 or status == 403:
                raise ProviderError("expired_source", http_status=status)
            if status == 404:
                raise ProviderError("media_unavailable", http_status=404)
            if not 200 <= status < 300:
                raise ProviderError("media_http_error", http_status=status)
            if len(raw) > self._max:
                raise ProviderError("oversize_payload")
            return raw, (headers or {}).get("content-type", "")
        raise ProviderError("redirect_limit")

    def refresh_url(self, post_id):
        """Approved refresh path for expired media links: re-resolve the
        post and return its fresh media URL (token-redacted in logs)."""
        payload = self._metadata(post_id)
        url = payload.get("media_url")
        if not url:
            raise ProviderError("no_media_url")
        return url

    @staticmethod
    def redacted(payload):
        return redact(payload)
