"""Bounded public HTTPS reads with redirects handled by the caller."""
import urllib.request
import urllib.error
import math
from ..execution.policy import ExecutionPolicy
from ..testing.fakes import ProviderError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class BoundedHTTP:
    def __init__(self, capability, policy=None, max_bytes=512 * 1024 * 1024, *, timeout_s=60):
        self.policy = policy or ExecutionPolicy()
        self.capability = capability
        self.policy.require_live(capability)
        self.maximum = max_bytes
        if not isinstance(timeout_s,(int,float)) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 600:
            raise ValueError('HTTP timeout must be finite and between 0 and 600 seconds')
        self.timeout_s=timeout_s

    def __call__(self, method, url, body=None, headers=None):
        self.policy.require_live(self.capability)
        request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=self.timeout_s)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > self.maximum:
                raise ProviderError("oversize_payload")
            raw = response.read(self.maximum + 1)
            if len(raw) > self.maximum:
                raise ProviderError("oversize_payload")
            return response.status, {k.lower(): v for k, v in response.headers.items()}, raw
