"""Small, non-retrying client for the official Viral Outliers REST API.

Paid requests are invoked only by viral_scan after its persisted credit gate.
The injectable transport returns (status, headers, JSON); it never sees a key.
"""
import json
import math
import urllib.error
import urllib.request

BASE_URL = "https://viraloutliers.com"
SEARCH_PATH = "/api/v1/search/content"


class ViralError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def nonnegative_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ViralError("Viral Outliers returned an invalid numeric field")
    if not math.isfinite(value) or value < 0:
        raise ViralError("Viral Outliers returned an invalid numeric field")
    return value


class ViralOutliersClient:
    def __init__(self, key="", transport=None):
        self._key = key
        self._transport = transport or self._http

    def _http(self, method, path, body):
        headers = {"User-Agent": "ShortFormRadar/1.0", "Accept": "application/json"}
        if path not in ("/api/v1/pricing", "/api/v1/trending"):
            if not self._key:
                raise ViralError("Set VIRAL_OUTLIERS_API_KEY in the project .env")
            headers["Authorization"] = "Bearer " + self._key
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.build_opener(_NoRedirect()).open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        except (OSError, ValueError):
            raise ViralError("Viral Outliers connection failed; request outcome may be unknown") from None
        with response:
            status = response.code
            safe_headers = {k.lower(): v for k, v in response.headers.items()
                            if k.lower() in ("x-credits-charged", "x-credits-balance")}
            raw = response.read().decode("utf-8", errors="replace")
        if self._key:
            raw = raw.replace(self._key, "[redacted]")
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        return status, safe_headers, payload

    def request(self, method, path, body=None):
        if (method, path) not in {
            ("GET", "/api/v1/credits"), ("GET", "/api/v1/pricing"),
            ("GET", "/api/v1/trending"), ("POST", SEARCH_PATH),
        }:
            raise ViralError("Unsupported Viral Outliers endpoint")
        return self._transport(method, path, body)

    @staticmethod
    def checked(response):
        status, _, payload = response
        if status in (401, 403):
            raise ViralError("Viral Outliers rejected the API key; check the account/key in .env")
        if status == 402:
            raise ViralError("Viral Outliers has insufficient available API credits")
        if status == 429:
            raise ViralError("Viral Outliers rate limit reached; no automatic retry")
        if not 200 <= status < 300:
            raise ViralError(f"Viral Outliers returned HTTP {status}; no automatic retry")
        if not isinstance(payload, dict) or payload.get("error") or payload.get("success") is False:
            raise ViralError("Viral Outliers returned an invalid response; review the saved receipt")
        return payload

    def credits(self):
        payload = self.checked(self.request("GET", "/api/v1/credits"))
        return nonnegative_number(payload.get("balance"))

    def pricing(self):
        payload = self.checked(self.request("GET", "/api/v1/pricing"))
        try:
            search = next(s for s in payload["skills"] if s["key"] == "search_outliers")
            price = nonnegative_number(search["credits"])
            usd = nonnegative_number(payload["usdPerCredit"])
            if search["restMethod"] != "POST" or search["restPath"] != SEARCH_PATH:
                raise ValueError
        except (KeyError, TypeError, StopIteration, ValueError):
            raise ViralError("Viral Outliers search pricing could not be verified") from None
        return {"credits_per_search": price, "usd_per_credit": usd}

    def doctor(self):
        return {"provider": "viral-outliers", "authenticated": True,
                "available_credits": self.credits(), **self.pricing()}

    def trending(self):
        return self.checked(self.request("GET", "/api/v1/trending"))
