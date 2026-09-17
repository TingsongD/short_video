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
REPORTING_API = "https://youtubereporting.googleapis.com/v1/jobs"
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

    def _call(self, url, oauth=False, format=None):
        req = {"url": url, "headers": {}, "format":format}
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

    def _pages(self,url,key):
        rows=[];seen=set();token=''
        for _ in range(100):
            target=url+('&' if '?' in url else '?')+_q({'pageToken':token}) if token else url
            result=self._call(target,oauth=True);rows.extend(result.get(key) or [])
            token=result.get('nextPageToken')
            if not token:return rows
            if token in seen:raise AnalyticsTransportError('pagination_cycle')
            seen.add(token)
        raise AnalyticsTransportError('pagination_limit')

    def reach_jobs(self):
        return [j for j in self._pages(REPORTING_API,'jobs') if j.get('reportTypeId')==REACH_REPORT]

    def create_reach_job(self,name):
        # A remote configuration mutation: an effect-scoped setup action is
        # required, and discovery precedes creation after an uncertain reply.
        from ..execution.context import current_effect
        binding=current_effect.get()
        if not binding or binding.get('provider')!='youtube_reporting':raise AnalyticsTransportError('authority_required')
        existing=self.reach_jobs()
        if existing:return existing[0]
        response=self.transport({'url':REPORTING_API,'method':'POST','headers':{'Authorization':'Bearer '+self.oauth_token},'body':{'name':name,'reportTypeId':REACH_REPORT}})
        if response.get('status',200)>=400:raise AnalyticsTransportError('report_job_creation_failed',response['status'])
        body=response.get('body') or {}
        if not body.get('id') or body.get('reportTypeId')!=REACH_REPORT:raise AnalyticsTransportError('invalid_report_job')
        return body

    def thumbnail_reach(self,video_id,start_date,end_date):
        import csv,io
        columns=['day']+sorted(REACH_METRICS);jobs=self.reach_jobs()
        if not jobs:return {'report':REACH_REPORT,'columns':columns,'rows':[],'availability':'report_job_missing','report_ids':[]}
        reports=[]
        for job in jobs:
            reports.extend(self._pages(REPORTING_API+'/'+urllib.parse.quote(job['id'],safe='')+'/reports','reports'))
        # Newer regenerated files replace the same channel/video/day evidence.
        chosen={};ids=[]
        for report in sorted(reports,key=lambda r:r.get('createTime','')):
            url=report.get('downloadUrl','');parsed=urllib.parse.urlsplit(url)
            if parsed.scheme!='https' or parsed.hostname not in ('youtubereporting.googleapis.com','www.googleapis.com') or parsed.username or parsed.port not in (None,443):raise AnalyticsTransportError('untrusted_report_url')
            payload=self._call(url,oauth=True,format="csv")
            if not isinstance(payload,(str,bytes)):raise AnalyticsTransportError('report_csv_required')
            if len(payload)>32*1024*1024:raise AnalyticsTransportError('report_too_large')
            if isinstance(payload,bytes):payload=payload.decode('utf-8-sig')
            reader=csv.DictReader(io.StringIO(payload))
            if not {'date','video_id','channel_id',*REACH_METRICS}<=set(reader.fieldnames or []):raise AnalyticsTransportError('invalid_report_columns')
            ids.append(report.get('id'))
            for row in reader:
                day=row['date'];day=day[:4]+'-'+day[4:6]+'-'+day[6:] if len(day)==8 else day
                if row['video_id']!=video_id or not start_date<=day<=end_date:continue
                try:values=[float(row[m]) if row[m]!='' else None for m in sorted(REACH_METRICS)]
                except ValueError:raise AnalyticsTransportError('invalid_report_number') from None
                chosen[(day,row['channel_id'],video_id)]=[day]+values
        return {'report':REACH_REPORT,'columns':columns,'rows':list(chosen.values()),'report_ids':ids,
                'timezone':'America/Los_Angeles','availability':'ok' if chosen else 'no_rows_yet'}

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
        views = [int(v["statistics"]["viewCount"])
                 for v in self._call(url).get("items", []) if v.get("statistics",{}).get("viewCount") is not None]
        if not views:
            return None, "no_statistics"
        views.sort()
        mid = len(views) // 2
        median = (views[mid] if len(views) % 2
                  else (views[mid - 1] + views[mid]) / 2)
        return float(median), "ok"
