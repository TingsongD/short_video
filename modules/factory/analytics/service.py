"""Analytics readback service (F32): due horizons from ACTUAL
publication times, supported queries only, raw + normalized storage,
explicit missingness, matched-horizon comparison, manual import.

- Horizons 48h/7d/28d derive from `published_at` — not pull time.
- One MetricSnapshot per (publication, horizon, query_version):
  retries update it; a delayed retry is never a new independent
  sample.
- Zero, missing, delayed, unsupported and failed are distinct.
  `metrics` values stay nullable; `availability` carries the reason.
- Retention-style metrics are stored natively — a value above 1 (or
  100%) is preserved, never clamped.
"""
import json
from datetime import datetime, timedelta, timezone

from ..domain.errors import ContractError
from ..domain.records import MetricSnapshot
from .client import (ANALYTICS_PER_VIDEO, AnalyticsTransportError,
                     REACH_METRICS)

HORIZONS = {"24h": 24, "48h": 48, "72h": 72, "7d": 168, "28d": 672}
# Complete source-reporting-day windows (PL-04). Only platforms with a
# qualified reporting-window source may collect these — see
# WINDOW_SOURCES / window_capability.
COMPLETE_DAYS = {"7d_complete": 7, "28d_complete": 28}
QUERY_VERSION = "f32.v2"

PULL_METRICS = {"views", "averageViewDuration",
                "averageViewPercentage", "subscribersGained",
                "likes", "comments", "shares", "engagedViews"}

# normalized metric -> (source route, source column)
NORMALIZED = {
    "views": ("analytics", "views"),
    "avg_view_duration_s": ("analytics", "averageViewDuration"),
    "avg_view_pct": ("analytics", "averageViewPercentage"),
    "subs_gained": ("analytics", "subscribersGained"),
    "likes": ("analytics", "likes"),
    "comments": ("analytics", "comments"),
    "shares": ("analytics", "shares"),
    "thumbnail_impressions": ("reach",
                              "video_thumbnail_impressions"),
    "thumbnail_ctr": ("reach",
                      "video_thumbnail_impressions_ctr"),
    "public_views": ("data", "viewCount"),
    "engaged_views": ("analytics", "engagedViews"),
}

# Metrics a snapshot may legitimately lack without downgrading —
# lifetime counters, optional reach-route thumbnail fields and other
# provider-optional columns (§8.2: "missing optional thumbnail reach
# must not prevent a valid Shorts comparison"). The decision layer
# consumes only policy-declared metrics; absence stays recorded.
OPTIONAL_COMPLETENESS = {"public_views", "engaged_views", "shares",
                         "thumbnail_impressions", "thumbnail_ctr"}

# Per-platform normalized metric -> provider field (PL-04). The
# YouTube entry is the historical route-based map above; other
# platforms normalize publisher analytics responses. Provider field
# names are provisional until live-qualified (handover §8.3).
PLATFORM_METRICS = {
    "youtube": NORMALIZED,
    "tiktok": {"views": "views", "likes": "likes", "comments": "comments",
               "shares": "shares", "saves": "saves",
               "avg_view_duration_s": "avg_watch_time_s",
               "avg_view_pct": "completion_rate"},
    "instagram": {"views": "views", "likes": "likes",
                  "comments": "comments", "shares": "shares",
                  "saves": "saves", "reach": "reach",
                  "avg_view_duration_s": "avg_watch_time_s",
                  "avg_view_pct": "completion_rate"},
    "facebook": {"views": "views", "likes": "likes",
                 "comments": "comments", "shares": "shares",
                 "saves": "saves", "reach": "reach",
                 "avg_view_duration_s": "avg_watch_time_s",
                 "avg_view_pct": "completion_rate"},
}

# Which window kinds a qualified source can supply per platform
# (handover §8.2 gate). Publisher caches deliver captured-at snapshots
# only — they never supply source_calendar_window. Extend when a route
# is live-qualified; never declare a kind a route cannot prove.
WINDOW_SOURCES = {
    "youtube": {"observed_lifetime_at_age": "youtube_analytics",
                "source_calendar_window": "youtube_analytics",
                "exact_elapsed_window": "youtube_analytics_day_aligned"},
    "tiktok": {"observed_lifetime_at_age": "publisher"},
    "instagram": {"observed_lifetime_at_age": "publisher"},
    "facebook": {"observed_lifetime_at_age": "publisher"},
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(dt):
    return dt.date().isoformat()


class ReadbackService:
    def __init__(self, db, client,clock=None,publisher_metrics=None):
        self.db = db
        self.client = client
        self.clock=clock or _now
        # {provider_name: callable(remote_post_id, post_url) -> dict}
        # for non-YouTube platforms measured through a publisher (PL-04).
        self.publisher_metrics = publisher_metrics or {}

    def window_capability(self, platform, window_kind):
        """Qualified source name for (platform, window_kind) or None —
        the §8.2 freeze gate consults this; it is honest, not optimistic."""
        return WINDOW_SOURCES.get(platform or "youtube", {}).get(window_kind)

    def _window_for(self, pub, horizon, t0):
        """(start, end, due_at, window_kind) for a collect call.
        Elapsed horizons keep the existing LA-day logic; complete-days
        horizons take the N source days after the partial publish day."""
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('America/Los_Angeles')
        if horizon in COMPLETE_DAYS:
            platform = pub.get('platform', 'youtube')
            if self.window_capability(platform, 'source_calendar_window') is None:
                raise ContractError('window_capability_missing', 'horizon',
                                    f'{platform}:{horizon}')
            days = COMPLETE_DAYS[horizon]
            local_t0 = t0.astimezone(zone)
            pub_day = local_t0.date()
            # §8.2: exclude a partial publication day, but include it
            # when it begins exactly at the source-day boundary.
            aligned = local_t0 == datetime.combine(
                pub_day, datetime.min.time(), tzinfo=zone)
            start_d = pub_day if aligned else pub_day + timedelta(days=1)
            end_d = start_d + timedelta(days=days - 1)
            # eligible once the final source day has fully ended
            due_local = datetime.combine(
                end_d + timedelta(days=1), datetime.min.time(),
                tzinfo=zone)
            return (start_d.isoformat(), end_d.isoformat(),
                    due_local.astimezone(timezone.utc),
                    'source_calendar_window')
        due_at = t0 + timedelta(hours=HORIZONS[horizon])
        if pub.get('platform', 'youtube') != 'youtube':
            # A publisher cache captures counters AT an age — never a
            # source-reporting-day window (handover §8.1).
            return (_day(t0.astimezone(zone)),
                    _day(due_at.astimezone(zone)),
                    due_at, 'observed_lifetime_at_age')
        local_start=t0.astimezone(zone);local_end=due_at.astimezone(zone)
        exact=all(x.hour==x.minute==x.second==x.microsecond==0 for x in (local_start,local_end))
        return (_day(local_start),
                _day(local_end-timedelta(microseconds=1)),
                due_at,
                'exact_rolling' if exact else 'source_calendar')

    # -------------------------------------------------------- due --

    def due(self, publication_id, now=""):
        """Horizon states derived from the ACTUAL published_at."""
        now = now or self.clock()
        pub = self._pub(publication_id)
        if not pub or pub["status"] != "public" or \
                not pub.get("published_at"):
            raise ContractError("publication_not_public", "id",
                                publication_id)
        t0 = _parse(pub["published_at"])
        out = []
        due_map = {n: t0 + timedelta(hours=h)
                   for n, h in HORIZONS.items()}
        for name in COMPLETE_DAYS:
            try:
                _, _, d, _ = self._window_for(pub, name, t0)
                due_map[name] = d
            except ContractError:
                continue  # platform lacks a qualified reporting window
        for name, due_at in due_map.items():
            snap = self._snap(publication_id, name)
            if _parse(now) < due_at:
                status = "not_due"
            elif snap is None:
                status = "due"
            elif snap["completeness"] in ("complete",):
                status = "complete"
            elif snap["completeness"] in ("partial",):
                status = "partial"
            else:
                status = "due"          # pending/failed → retryable
            out.append({"horizon": name, "due_at": due_at.isoformat(),
                        "status": status,
                        "snapshot": (snap or {}).get("id")})
        return out

    # ----------------------------------------------------- collect --

    def collect(self, publication_id, horizon, now=""):
        """Pull all three routes for one due horizon; store raw +
        normalized snapshot. Idempotent per (pub, horizon, version)."""
        now = now or self.clock()
        if horizon not in HORIZONS and horizon not in COMPLETE_DAYS:
            raise ContractError("unknown_horizon", "horizon", horizon)
        pub = self._pub(publication_id)
        if not pub or pub["status"] != "public":
            raise ContractError("publication_not_public", "id",
                                publication_id)
        t0 = _parse(pub["published_at"])
        start, end, due_at, window_kind = self._window_for(
            pub, horizon, t0)
        if _parse(now) < due_at:
            raise ContractError("horizon_not_due", "horizon", horizon)
        post_id = pub["remote_post_id"]
        if pub.get("platform", "youtube") != "youtube":
            return self._collect_platform(
                pub, publication_id, horizon, now, start, end,
                due_at, window_kind, t0)
        if self.client is None:
            raise ContractError("metrics_route_unconfigured", "youtube")
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('America/Los_Angeles')
        local_start=t0.astimezone(zone);local_end=due_at.astimezone(zone)
        exact=all(x.hour==x.minute==x.second==x.microsecond==0 for x in (local_start,local_end))
        # Expected days = the requested window's days — for complete-
        # days horizons that is start..end (publish day excluded unless
        # midnight-aligned), matching the query actually sent.
        expected_days=[];cursor=datetime.fromisoformat(start).date()
        while cursor<=datetime.fromisoformat(end).date():
            expected_days.append(cursor.isoformat());cursor+=timedelta(days=1)
        sid = self._snap_id(publication_id, horizon)
        existing = self._snap(publication_id, horizon)
        attempts = (existing or {}).get("attempts", 0) + 1

        raw, metrics, availability = {}, {}, {}
        failures = []
        try:
            raw["data"] = self.client.data_api_stats(post_id)
        except AnalyticsTransportError as e:
            raw["data_error"] = str(e)
            failures.append("data_api")
        try:
            raw["analytics"] = self.client.analytics_report(
                post_id, start, end, sorted(PULL_METRICS))
        except AnalyticsTransportError as e:
            raw["analytics_error"] = str(e)
            failures.append("analytics_api")
        try:
            raw["reach"] = self.client.thumbnail_reach(
                post_id, start, end)
        except AnalyticsTransportError as e:
            raw["reach_error"] = str(e)
            failures.append("reporting_api")

        # Preserve raw protocol replies; normalization uses only the requested
        # source days. A lifetime Data API counter is never a timed metric.
        coverage = self._coverage(raw,start,end)
        coverage['expected_days']=expected_days
        coverage['exact_horizon']=exact
        coverage['metrics']={}
        for name,(route,col) in NORMALIZED.items():
            body=raw.get(route) or {};cols=body.get('columns',[]) if isinstance(body,dict) else []
            days=[]
            if col in cols and 'day' in cols:
                days=sorted({r[cols.index('day')] for r in body.get('rows',[]) if len(r)==len(cols) and start<=r[cols.index('day')]<=end and r[cols.index(col)] is not None})
            coverage['metrics'][name]={'days':days,'complete':route!='data' and days==expected_days,'window':'lifetime' if route=='data' else 'source_calendar'}
        normalized=dict(raw)
        for route in ('analytics','reach'):
            if isinstance(raw.get(route),dict):
                body=raw[route];cols=body.get('columns',[])
                if 'day' in cols:normalized[route]={**body,'rows':[r for r in body.get('rows',[]) if len(r)==len(cols) and start<=r[cols.index('day')]<=end]}
        for name, (route, col) in NORMALIZED.items():
            value, reason, denominator = self._extract(
                normalized, route, col)
            metrics[name] = value
            availability[name] = reason
            coverage['metrics'][name]['denominator'] = denominator
        coverage['failed_routes'] = list(failures)
        required_bad = [
            m for m in NORMALIZED if m not in OPTIONAL_COMPLETENESS
            and (not coverage['metrics'][m]['complete']
                 or availability[m] != 'ok')]
        # Optional-only routes (data api, reach) carry no required
        # metric — their failure degrades the snapshot but cannot block
        # a usable one (§8.2 required-metric readiness). A failed
        # analytics route is blocking: it feeds required metrics.
        blocking = [f for f in failures if f == "analytics_api"]
        if len(failures) == 3:
            completeness = "failed"
            reason = f"routes_failed:{','.join(failures)}"
        elif blocking:
            completeness = "partial"
            reason = f"routes_failed:{','.join(failures)}"
        elif not coverage['routes']['analytics']['days']:
            # pending means the core analytics route has no source days
            # yet — optional reach-route absence never forces pending.
            completeness = "pending"
            reason = "no_rows_yet"
        elif required_bad:
            completeness = "partial"
            reason = "coverage_short_of_horizon"
        else:
            # Coverage is complete for the requested source days. Whether
            # the days form an exact elapsed window is recorded in
            # coverage['exact_horizon'] and requested_period.window_kind —
            # it qualifies the measurement definition, not completeness.
            completeness = "complete"
            reason = ""

        snap = MetricSnapshot(
            schema_version="metric_snapshot.v1", id=sid,
            created_at=(existing or {}).get("created_at", now),
            publication_id=publication_id, post_id=post_id,
            horizon=horizon, query_version=QUERY_VERSION,
            timezone="America/Los_Angeles",
            metric_definitions={
                "analytics_metrics": sorted(PULL_METRICS),
                "reach_metrics": sorted(REACH_METRICS),
                "reach_report": "channel_reach_basic_a1",'public_views':'lifetime_at_observation',
                'thumbnail_ctr':'impression-weighted percent','avg_view_duration_s':'engaged-view weighted seconds (views fallback)',
                'avg_view_pct':'engaged-view weighted percent (views fallback)'},
            requested_period={"start": start, "end": end,
                              "horizon_hours": (COMPLETE_DAYS.get(horizon, 0) * 24 or HORIZONS.get(horizon)),
                              'window_kind': window_kind,
                              'published_at':t0.isoformat(),'due_at':due_at.isoformat()},
            actual_coverage=coverage,
            source="data_api+analytics_api+reporting_api",
            observed_at=now, metrics=metrics,
            availability=availability, raw=raw, attempts=attempts,
            completeness=completeness, missing_reason=reason)
        snap.validate_or_raise()
        self._put(snap)
        self._event(publication_id, "readback_collected",
                    {"horizon": horizon, "completeness": completeness,
                     "attempt": attempts})
        return snap

    # ------------------------------------------- other platforms --

    def _collect_platform(self, pub, publication_id, horizon, now,
                          start, end, due_at, window_kind, t0):
        """Publisher-route collection for non-YouTube destinations
        (PL-04). Same MetricSnapshot shape; raw provider response
        preserved; upstream freshness recorded separately from our
        fetch time; missing fields are null with a reason."""
        platform = pub.get("platform", "")
        provider = pub.get("provider", "upload_post")
        fetch = self.publisher_metrics.get(provider)
        metrics_map = PLATFORM_METRICS.get(platform, {})
        sid = self._snap_id(publication_id, horizon)
        existing = self._snap(publication_id, horizon)
        attempts = (existing or {}).get("attempts", 0) + 1
        raw, metrics, availability = {}, {}, {}
        upstream_freshness = ""
        if fetch is None:
            for name in metrics_map:
                metrics[name] = None
                availability[name] = "route_unconfigured"
            completeness, reason = "failed", "metrics_route_unconfigured"
        else:
            try:
                raw["publisher"] = fetch(pub.get("remote_post_id", ""),
                                         pub.get("post_url", ""))
            except Exception as e:
                raw["publisher_error"] = str(e)
                for name in metrics_map:
                    metrics[name] = None
                    availability[name] = "route_failed"
                completeness, reason = "failed", "route_failed:publisher"
            else:
                body = raw["publisher"] or {}
                upstream_freshness = (body.get("fetched_at") or
                                      body.get("updated_at") or "")
                missing = []
                for name, field_name in metrics_map.items():
                    value = body.get(field_name)
                    if value is None:
                        metrics[name] = None
                        availability[name] = "field_absent"
                        missing.append(name)
                    else:
                        metrics[name] = value
                        availability[name] = "ok"
                completeness = "partial" if missing else "complete"
                reason = ("missing:" + ",".join(missing)) if missing else ""
        # observed age vs requested age — late evidence stays honest
        age_s = (_parse(now) - t0).total_seconds()
        requested_s = (COMPLETE_DAYS.get(horizon, 0) * 86400 or
                       HORIZONS.get(horizon, 0) * 3600)
        late = requested_s and age_s > requested_s * 1.25
        snap = MetricSnapshot(
            schema_version="metric_snapshot.v1", id=sid,
            created_at=(existing or {}).get("created_at", now),
            publication_id=publication_id,
            post_id=pub.get("remote_post_id", ""),
            horizon=horizon, query_version=QUERY_VERSION,
            timezone=pub.get("timezone", "UTC"),
            metric_definitions={"platform": platform,
                                "field_map": dict(metrics_map)},
            requested_period={
                "window_kind": window_kind,
                "horizon_hours": requested_s / 3600,
                "published_at": t0.isoformat(),
                "due_at": due_at.isoformat(),
                "observed_at": now,
                "upstream_freshness": upstream_freshness},
            actual_coverage={"observed_age_hours": round(age_s / 3600, 2),
                             "requested_age_hours": requested_s / 3600,
                             "late": bool(late)},
            source=f"{provider}_publisher",
            observed_at=now, metrics=metrics,
            availability=availability, raw=raw, attempts=attempts,
            completeness=completeness, missing_reason=reason)
        snap.validate_or_raise()
        self._put(snap)
        self._event(publication_id, "readback_collected",
                    {"horizon": horizon, "completeness": completeness,
                     "attempt": attempts, "platform": platform})
        return snap

    def _extract(self, raw, route, col):
        """(value|None, reason) — distinguish zero/missing/delayed/
        unsupported/failed. Values pass through natively (retention
        may exceed 1; never clamped)."""
        key = {"data": "data", "analytics": "analytics",
               "reach": "reach"}[route]
        if f"{key}_error" in raw:
            return None, "route_failed", None
        body = raw.get(key)
        if body is None:
            return None, "route_not_queried", None
        if route == "data":
            v = body.get(col)
            return ((int(v), "ok", None) if v is not None else
                    (None, "field_absent", None))
        cols, rows = body.get("columns", []), body.get("rows", [])
        if col not in cols:
            return None, "metric_not_returned", None
        if not rows:
            return None, "no_rows_yet", None
        import math
        idx=cols.index(col)
        if any(len(r)!=len(cols) for r in rows):return None,'malformed_rows',None
        vals=[r[idx] for r in rows]
        if all(v is None for v in vals):return None,'all_rows_null',None
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in vals):return None,'incomplete_or_invalid_rows',None
        # §8.1: weight daily averages by the matching engaged-view
        # denominator when supplied; fall back to same-day views — a
        # per-day source metric, never the public lifetime counter.
        weight={'averageViewDuration':('engagedViews','views'),
                'averageViewPercentage':('engagedViews','views'),
                'video_thumbnail_impressions_ctr':(
                    'video_thumbnail_impressions',)}.get(col,())
        for wcol in weight:
            if wcol not in cols:continue
            weights=[r[cols.index(wcol)] for r in rows]
            if any(type(w) not in (int,float) or not math.isfinite(w)
                   or w<0 for w in weights):continue
            total=sum(weights)
            if total<=0:continue
            return sum(v*w for v,w in zip(vals,weights))/total,'ok',wcol
        if weight:return None,'zero_denominator',None
        return sum(vals),'ok',None

    def _coverage(self,raw,start='',end='9999-99-99'):
        routes={}
        for key in ('analytics','reach'):
            body=raw.get(key) or {};cols=body.get('columns',[]);days=[]
            if 'day' in cols:days=sorted({r[cols.index('day')] for r in body.get('rows',[]) if len(r)==len(cols) and start<=r[cols.index('day')]<=end})
            routes[key]={'days':days,'start':days[0] if days else '', 'end':days[-1] if days else ''}
        common=sorted(set(routes['analytics']['days']) & set(routes['reach']['days']))
        return {'start':common[0] if common else '', 'end':common[-1] if common else '', 'days':len(common),'routes':routes}

    # ---------------------------------------------------- baseline --

    def baseline(self, handle="", now=""):
        """Observed channel baseline — unknown stays unknown."""
        value, reason = self.client.channel_median(handle)
        return {"median": value, "reason": reason,
                "observed_at": now or _now()}

    # ------------------------------------------------------ manual --

    def import_manual(self, publication_id, *, metrics, period,
                      confidence, source_name, now=""):
        """Manual metric import for platforms without a qualified
        connector — explicit source, period and confidence; only the
        metrics actually observed are stored (never invented)."""
        now = now or _now()
        if not metrics or not isinstance(metrics, dict):
            raise ContractError("missing_metrics", "metrics")
        if confidence not in ("low", "medium", "high"):
            raise ContractError("bad_confidence", "confidence",
                                confidence)
        if not period.get("start") or not period.get("end"):
            raise ContractError("missing_period", "period")
        if not source_name:
            raise ContractError("missing_source", "source_name")
        pub = self._pub(publication_id)
        if not pub:
            raise ContractError("unknown_publication", "id",
                                publication_id)
        sid = f"snap-{publication_id}-manual-{source_name}"
        snap = MetricSnapshot(
            schema_version="metric_snapshot.v1", id=sid,
            created_at=now, publication_id=publication_id,
            post_id=pub.get("remote_post_id", ""),
            horizon="manual", query_version=QUERY_VERSION,
            timezone=pub.get("timezone", "UTC"),
            requested_period=dict(period),
            actual_coverage=dict(period),
            source=f"manual:{source_name}", observed_at=now,
            metrics={k: v for k, v in metrics.items()},
            availability={k: "manual" for k in metrics},
            completeness="complete",
            missing_reason="",
            raw={"imported": dict(metrics),
                 "confidence": confidence})
        snap.validate_or_raise()
        self._put(snap)
        self._event(publication_id, "manual_metrics_imported",
                    {"source": source_name, "confidence": confidence})
        return snap

    # ----------------------------------------------------- compare --

    def compare(self, publication_ids, horizon):
        """Matched-horizon descriptive comparison. Incomplete coverage
        stays pending — never counted as a zero sample."""
        entries = []
        for pid in publication_ids:
            snap = self._snap(pid, horizon)
            if snap is None or snap["completeness"] in (
                    "pending", "failed"):
                entries.append({"publication_id": pid,
                                "status": "pending", "metrics": {}})
            else:
                entries.append({"publication_id": pid,
                                "status": snap["completeness"],
                                "metrics": snap["metrics"]})
        signatures=[]
        for pid in publication_ids:
            snap=self._snap(pid,horizon)
            if snap:signatures.append((snap['query_version'],snap['timezone'],snap.get('requested_period',{}).get('horizon_hours'),snap.get('requested_period',{}).get('window_kind'),json.dumps(snap.get('metric_definitions',{}),sort_keys=True)))
        comparable = bool(entries) and all(e['status']=='complete' for e in entries) and len(set(signatures))==1 and signatures[0][3]=='exact_rolling'
        return {"horizon": horizon, "comparable": comparable,
                "descriptive": True,
                "note": "observational, not a causal A/B claim",
                "entries": entries}

    # ---------------------------------------------------------- io --

    def get_snapshot(self, publication_id, horizon):
        return self._snap(publication_id, horizon)

    def _snap_id(self, publication_id, horizon):
        from ..domain.records import content_hash
        return 'snap-'+content_hash([publication_id,horizon,QUERY_VERSION])[:32]

    def _snap(self, publication_id, horizon):
        row = self.db.uow().records.get(
            "metricsnapshot", self._snap_id(publication_id, horizon))
        return json.loads(row["body"]) if row else None

    def _pub(self, publication_id):
        row = self.db.uow().records.get("publication", publication_id)
        return json.loads(row["body"]) if row else None

    def _put(self, snap):
        row = self.db.uow().records.get("metricsnapshot", snap.id)
        if row is None:
            with self.db.uow() as u:
                u.records.put(snap)
            return
        # A retry is another immutable observation revision, not a new sample.
        snap.revision=row['revision']+1
        with self.db.uow() as u:u.records.put(snap)

    def _event(self, publication_id, kind, body):
        with self.db.uow() as u:
            u.events.append(f"publication:{publication_id}", kind, body)
