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

HORIZONS = {"48h": 48, "7d": 168, "28d": 672}
QUERY_VERSION = "f32.v2"

PULL_METRICS = {"views", "averageViewDuration",
                "averageViewPercentage", "subscribersGained",
                "likes", "comments"}

# normalized metric -> (source route, source column)
NORMALIZED = {
    "views": ("analytics", "views"),
    "avg_view_duration_s": ("analytics", "averageViewDuration"),
    "avg_view_pct": ("analytics", "averageViewPercentage"),
    "subs_gained": ("analytics", "subscribersGained"),
    "likes": ("analytics", "likes"),
    "comments": ("analytics", "comments"),
    "thumbnail_impressions": ("reach",
                              "video_thumbnail_impressions"),
    "thumbnail_ctr": ("reach",
                      "video_thumbnail_impressions_ctr"),
    "public_views": ("data", "viewCount"),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(dt):
    return dt.date().isoformat()


class ReadbackService:
    def __init__(self, db, client,clock=None):
        self.db = db
        self.client = client
        self.clock=clock or _now

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
        for name, hours in HORIZONS.items():
            due_at = t0 + timedelta(hours=hours)
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
        if horizon not in HORIZONS:
            raise ContractError("unknown_horizon", "horizon", horizon)
        pub = self._pub(publication_id)
        if not pub or pub["status"] != "public":
            raise ContractError("publication_not_public", "id",
                                publication_id)
        t0 = _parse(pub["published_at"])
        due_at = t0 + timedelta(hours=HORIZONS[horizon])
        if _parse(now) < due_at:
            raise ContractError("horizon_not_due", "horizon", horizon)
        post_id = pub["remote_post_id"]
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('America/Los_Angeles')
        local_start=t0.astimezone(zone);local_end=due_at.astimezone(zone)
        exact=all(x.hour==x.minute==x.second==x.microsecond==0 for x in (local_start,local_end))
        start=_day(local_start);end=_day(local_end-timedelta(microseconds=1))
        expected_days=[];cursor=local_start.date()
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
            value, reason = self._extract(normalized, route, col)
            metrics[name] = value
            availability[name] = reason
        if failures:
            completeness = ("failed" if len(failures) == 3
                            else "partial")
            reason = f"routes_failed:{','.join(failures)}"
        elif coverage["days"] == 0:
            completeness = "pending"
            reason = "no_rows_yet"
        elif any(not coverage['metrics'][m]['complete'] or availability[m]!='ok' for m in NORMALIZED if m!='public_views'):
            completeness = "partial"
            reason = "coverage_short_of_horizon"
        elif not exact:
            completeness='partial';reason='source_calendar_not_exact_horizon'
        else:
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
                'thumbnail_ctr':'impression-weighted percent','avg_view_duration_s':'view-weighted seconds',
                'avg_view_pct':'view-weighted percent'},
            requested_period={"start": start, "end": end,
                              "horizon_hours": HORIZONS[horizon],'window_kind':'exact_rolling' if exact else 'source_calendar',
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

    def _extract(self, raw, route, col):
        """(value|None, reason) — distinguish zero/missing/delayed/
        unsupported/failed. Values pass through natively (retention
        may exceed 1; never clamped)."""
        key = {"data": "data", "analytics": "analytics",
               "reach": "reach"}[route]
        if f"{key}_error" in raw:
            return None, "route_failed"
        body = raw.get(key)
        if body is None:
            return None, "route_not_queried"
        if route == "data":
            v = body.get(col)
            return (int(v), "ok") if v is not None else \
                (None, "field_absent")
        cols, rows = body.get("columns", []), body.get("rows", [])
        if col not in cols:
            return None, "metric_not_returned"
        if not rows:
            return None, "no_rows_yet"
        import math
        idx=cols.index(col)
        if any(len(r)!=len(cols) for r in rows):return None,'malformed_rows'
        vals=[r[idx] for r in rows]
        if all(v is None for v in vals):return None,'all_rows_null'
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in vals):return None,'incomplete_or_invalid_rows'
        weight={'averageViewDuration':'views','averageViewPercentage':'views','video_thumbnail_impressions_ctr':'video_thumbnail_impressions'}.get(col)
        if weight:
            if weight not in cols:return None,'denominator_missing'
            weights=[r[cols.index(weight)] for r in rows]
            if any(type(w) not in (int,float) or not math.isfinite(w) or w<0 for w in weights):return None,'denominator_missing'
            total=sum(weights)
            if total==0:return None,'zero_denominator'
            return sum(v*w for v,w in zip(vals,weights))/total,'ok'
        return sum(vals),'ok'

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
