"""Minimal YouTube Data API v3 client over stdlib urllib (same approach as the
vendored yt-competitive-analysis script). `transport` is injectable so tests
can serve fixtures with zero network; the real transport charges quota first."""
import json
import urllib.parse
import urllib.request

from .quota import QuotaManager


class YouTubeClient:
    BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key, quota=None, transport=None):
        self.api_key = api_key
        self.quota = quota or QuotaManager(budget=10_000)
        self.transport = transport or self._live_transport

    def api_get(self, endpoint, **params):
        self.quota.charge(endpoint)
        return self.transport(endpoint, params)

    def _live_transport(self, endpoint, params):
        q = urllib.parse.urlencode({**params, "key": self.api_key})
        url = f"{self.BASE}/{endpoint}?{q}"
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
