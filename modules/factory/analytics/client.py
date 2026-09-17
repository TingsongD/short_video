"""Factory analytics client (F32): three DISTINCT query routes, each
with only currently supported endpoint/metric combinations.

- `data_api_stats` — YouTube Data API public statistics (key auth).
- `analytics_report` — YouTube Analytics API per-video report:
  views/AVD/retention-style metrics ONLY. Generic `impressions`/`ctr`
  are NOT valid per-video thumbnail-reach metrics and are refused.
- `thumbnail_reach` — YouTube Reporting API `channel_reach_basic_a1`
  report carrying `video_thumbnail_impressions` +
  `video_thumbnail_impressions_ctr`. Reach is collected separately —
  never substituted with ad impressions or a generic ctr.
- `channel_median` — own-channel recent-uploads median (Data API).
  Returns (value|None, reason): unavailable is unknown, never 0.0.

transport(request) -> {"status": int, "body": dict}; the fake
transport in testing.fakes asserts these wire contracts.
"""
import urllib.parse

DATA_API = "https://www.googleapis.com/youtube/v3/videos"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
REPORTING_API = "https://youtubereporting.googleapis.com/v1/reports"
CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_API = "https://www.googleapis.com/youtube/v3/playlistItems"

ANALYTICS_PER_VIDEO = {
    "views", "estimatedMinutesWatched", "averageViewDuration",
    "averageViewPercentage", "subscribersGained", "subscribersLost",
    "likes", "dislikes", "comments", "shares",
}
REACH_REPORT = "channel_reach_basic_a1"
REACH_METRICS = {
    "video_thumbnail_impressions", "video_thumbnail_impressions_ctr"}
RETENTION_METRICS = {"audienceWatchRatio", "relativeRetentionPerformance"}


class AnalyticsTransportError(Exception):
    def __init__(self, message, status_code=0, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _q(params):
    return urllib.parse.urlencode(params, doseq=True)


class FactoryAnalyticsClient:
    def __init__(self, yt_api_key="", oauth_token="", transport=None):
        self.yt_api_key = yt_api_key
        self.oauth_token = oauth_token
        self.transport = transport

    def _call(self, url, oauth=False):
        req = {"url": url, "headers": {}}
        if oauth:
            req["headers"]["Authorization"] = \
                f"Bearer {self.oauth_token}"
        resp = self.transport(req)
        status = resp.get("status", 200)
        if status >= 400:
            raise AnalyticsTransportError(
                f"analytics_http_{status}", status_code=status,
                body=resp.get("body"))
        return resp.get("body") or {}

    # ----------------------------------------------------- data api --

    def data_api_stats(self, video_id):
        """Public point-in-time statistics — no period, no coverage."""
        url = f"{DATA_API}?{_q({'id': video_id, 'part': 'statistics',
                              'key': self.yt_api_key})}"
        items = self._call(url).get("items") or []
        return dict(items[0].get("statistics", {})) if items else {}

    # ------------------------------------------------- analytics api --

    def analytics_report(self, video_id, start_date, end_date,
                         metrics, dimensions=("day",)):
        """Supported per-video metrics only; `dimensions=day` rows let
        the caller compute ACTUAL coverage (daily aggregates are not
        automatically exact rolling-age windows)."""
        bad = set(metrics) - ANALYTICS_PER_VIDEO
        if bad:
            raise ValueError(
                f"unsupported per-video analytics metrics: "
                f"{sorted(bad)} — thumbnail reach uses the Reporting "
                f"API {REACH_REPORT} report")
        url = f"{ANALYTICS_API}?{_q({
            'ids': 'channel==MINE', 'startDate': start_date,
            'endDate': end_date, 'metrics': ','.join(sorted(metrics)),
            'dimensions': ','.join(dimensions),
            'filters': f'video=={video_id}',
            'sort': 'day'})}"
        body = self._call(url, oauth=True)
        cols = [c["name"] for c in body.get("columnHeaders", [])]
        return {"columns": cols, "rows": body.get("rows") or []}

    # ------------------------------------------------- reporting api --

    def thumbnail_reach(self, video_id, start_date, end_date):
        """Thumbnail reach via the Reporting API — separate collection
        from per-video analytics."""
        url = f"{REPORTING_API}?{_q({
            'reportType': REACH_REPORT,
            'ids': 'channel==MINE', 'startDate': start_date,
            'endDate': end_date,
            'metrics': ','.join(sorted(REACH_METRICS)),
            'dimensions': 'day', 'filters': f'video=={video_id}',
            'sort': 'day'})}"
        body = self._call(url, oauth=True)
        cols = [c["name"] for c in body.get("columnHeaders", [])]
        return {"report": REACH_REPORT, "columns": cols,
                "rows": body.get("rows") or []}

    # ------------------------------------------------------ baseline --

    def channel_median(self, handle="", max_items=25):
        """(median|None, reason) — unknown stays unknown."""
        url = f"{CHANNELS_API}?{_q({'part': 'contentDetails',
                                  'forHandle': handle.lstrip('@'),
                                  'key': self.yt_api_key})}"
        items = self._call(url).get("items") or []
        if not items:
            return None, "channel_not_found"
        uploads = (items[0].get("contentDetails", {})
                   .get("relatedPlaylists", {}).get("uploads"))
        if not uploads:
            return None, "uploads_playlist_missing"
        url = f"{PLAYLIST_API}?{_q({
            'part': 'contentDetails', 'playlistId': uploads,
            'maxResults': min(max_items, 50), 'key': self.yt_api_key})}"
        ids = [it["contentDetails"]["videoId"]
               for it in self._call(url).get("items", [])
               if it.get("contentDetails", {}).get("videoId")][:max_items]
        if not ids:
            return None, "no_recent_uploads"
        url = f"{DATA_API}?{_q({'part': 'statistics',
                              'id': ','.join(ids),
                              'key': self.yt_api_key})}"
        views = [int(v.get("statistics", {}).get("viewCount", 0))
                 for v in self._call(url).get("items", [])]
        if not views:
            return None, "no_statistics"
        views.sort()
        mid = len(views) // 2
        median = (views[mid] if len(views) % 2
                  else (views[mid - 1] + views[mid]) / 2)
        return float(median), "ok"
