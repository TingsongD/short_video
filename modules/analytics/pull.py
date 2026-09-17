"""M10 pull: YouTube Data API (public stats) + YouTube Analytics API
(own-channel: impressions, CTR, AVD, retention). OAuth bearer token is read
from the path in secrets at call time — tests use a fake transport."""
import json
import urllib.parse
import urllib.request
from pathlib import Path

DATA_API = "https://www.googleapis.com/youtube/v3/videos"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_API = "https://www.googleapis.com/youtube/v3/playlistItems"


class AnalyticsClient:
    """transport(url) -> decoded JSON. YT key for Data API, OAuth for
    Analytics API (own-channel metrics)."""
    def __init__(self, yt_api_key="", oauth_token_path="", transport=None):
        self.yt_api_key = yt_api_key
        self.oauth_token_path = oauth_token_path
        self.transport = transport or self._http

    def _bearer(self):
        if not self.oauth_token_path:
            return ""
        data = json.loads(Path(self.oauth_token_path).read_text())
        return data.get("access_token", "")

    def _http(self, url):
        headers = {}
        if "youtubeanalytics" in url:
            headers["Authorization"] = f"Bearer {self._bearer()}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def public_stats(self, yt_video_id):
        q = urllib.parse.urlencode({
            "id": yt_video_id, "part": "statistics", "key": self.yt_api_key,
        })
        data = self.transport(f"{DATA_API}?{q}")
        items = data.get("items") or []
        return items[0].get("statistics", {}) if items else {}

    def analytics_rows(self, yt_video_id, start_date, end_date):
        """Views/AVD/subs for one video over a window. F32 fix: the
        generic `impressions,ctr` pair was never a supported per-video
        metric set — thumbnail reach lives on the Reporting API
        `channel_reach_basic_a1` report (see the factory client)."""
        q = urllib.parse.urlencode({
            "ids": "channel==MINE",
            "startDate": start_date, "endDate": end_date,
            "metrics": "views,averageViewDuration,averageViewPercentage,"
                       "subscribersGained",
            "filters": f"video=={yt_video_id}",
        })
        data = self.transport(f"{ANALYTICS_API}?{q}")
        cols = [c["name"] for c in data.get("columnHeaders", [])]
        rows = data.get("rows") or []
        return dict(zip(cols, rows[0])) if rows else {}

    def retention(self, yt_video_id, start_date, end_date):
        """audienceWatchRatio over elapsedVideoTimeRatio -> retention_points."""
        q = urllib.parse.urlencode({
            "ids": "channel==MINE",
            "startDate": start_date, "endDate": end_date,
            "metrics": "audienceWatchRatio",
            "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={yt_video_id}",
            "sort": "elapsedVideoTimeRatio",
        })
        data = self.transport(f"{ANALYTICS_API}?{q}")
        return [
            {"t_ratio": r[0], "audience_ratio": r[1]}
            for r in (data.get("rows") or [])
        ]

    def channel_median_views(self, handle="", max_items=25):
        """Median viewCount of our channel's recent uploads (Data API, key
        auth). Verdict/promotion baseline (B3). Legacy contract: returns
        0.0 when unavailable — see channel_median_views_observed() for
        the explicit unknown form."""
        value, _reason = self.channel_median_views_observed(
            handle, max_items)
        return value if value is not None else 0.0

    def channel_median_views_observed(self, handle="", max_items=25):
        """(median|None, reason) — an unavailable baseline is unknown,
        never a measured zero."""
        from modules.radar.metrics import channel_median
        q = urllib.parse.urlencode({"part": "contentDetails",
                                    "forHandle": handle.lstrip("@"),
                                    "key": self.yt_api_key})
        data = self.transport(f"{CHANNELS_API}?{q}")
        items = data.get("items") or []
        if not items:
            return None, "channel_not_found"
        uploads = (items[0].get("contentDetails", {})
                   .get("relatedPlaylists", {}).get("uploads"))
        if not uploads:
            return None, "uploads_playlist_missing"
        q = urllib.parse.urlencode({"part": "contentDetails", "playlistId": uploads,
                                    "maxResults": min(max_items, 50), "key": self.yt_api_key})
        data = self.transport(f"{PLAYLIST_API}?{q}")
        ids = [it["contentDetails"]["videoId"]
               for it in data.get("items", [])
               if it.get("contentDetails", {}).get("videoId")][:max_items]
        if not ids:
            return None, "no_recent_uploads"
        q = urllib.parse.urlencode({"part": "statistics", "id": ",".join(ids),
                                    "key": self.yt_api_key})
        data = self.transport(f"{DATA_API}?{q}")
        views = [int(v.get("statistics", {}).get("viewCount", 0))
                 for v in data.get("items", [])]
        if not views:
            return None, "no_statistics"
        return channel_median(views), "ok"
