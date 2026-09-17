"""Bounded public HTTPS reads with redirects handled by the caller."""
import urllib.request
import urllib.error
from ..execution.policy import ExecutionPolicy
from ..testing.fakes import ProviderError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class BoundedHTTP:
    def __init__(self, capability, policy=None, max_bytes=512 * 1024 * 1024):
        self.policy = policy or ExecutionPolicy()
        self.capability = capability
        self.policy.require_live(capability)
        self.maximum = max_bytes

    def __call__(self, method, url, body=None, headers=None):
        self.policy.require_live(self.capability)
        request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=60)
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
