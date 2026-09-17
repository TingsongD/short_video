"""CLI:
  python -m modules.analytics due            — list due window pulls
  python -m modules.analytics pull <video_id> <yt_id> --window 48h \
      --video-len-s 32                       — real pull (needs keys)
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from modules.common.config import DATA_DIR, secrets, system
from modules.publish.record import load_records

from .pull import AnalyticsClient
from .readback import load_or_new, record_window, write_readback
from .windows import due_windows


def main(argv=None):
    p = argparse.ArgumentParser(description="M10 Analytics Readback")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("due")
    pl = sub.add_parser("pull")
    pl.add_argument("video_id")
    pl.add_argument("youtube_id")
    pl.add_argument("--window", required=True, choices=["48h", "7d", "28d"])
    pl.add_argument("--video-len-s", type=float, required=True)
    args = p.parse_args(argv)

    cfg = system()["readback"]

    if args.cmd == "due":
        now = datetime.now(timezone.utc)
        any_due = False
        for r in load_records():
            existing = load_or_new(r["video_id"]).get("windows", {})
            due = due_windows(r, existing, cfg["windows_hours"], now)
            if due:
                any_due = True
                print(f"{r['video_id']} (yt:{r['platform_video_ids'].get('youtube')}): due {due}")
        if not any_due:
            print("no windows due")
        return 0

    sec = secrets()
    client = AnalyticsClient(
        yt_api_key=sec.get("YOUTUBE_API_KEY", ""),
        oauth_token_path=sec.get("YT_ANALYTICS_TOKEN", ""),
    )
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from modules.factory.analytics.service import HORIZONS
    record=next((r for r in load_records() if r['video_id']==args.video_id and r.get('platform_video_ids',{}).get('youtube')==args.youtube_id),None)
    if not record or not record.get('published_at'):p.error('Verified publication time is required for a timed readback')
    t0=datetime.fromisoformat(record['published_at'].replace('Z','+00:00'));due=t0+timedelta(hours=HORIZONS[args.window])
    if datetime.now(timezone.utc)<due:p.error('The requested readback horizon is not due')
    local=t0.astimezone(ZoneInfo('America/Los_Angeles'));last=due.astimezone(ZoneInfo('America/Los_Angeles'))
    exact=all(t.hour==t.minute==t.second==t.microsecond==0 for t in (local,last))
    start=local.date().isoformat();end=(last-timedelta(microseconds=1)).date().isoformat()
    stats = client.analytics_rows(args.youtube_id, start, end)
    window = {
        "pulled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "views": int(stats.get("views", 0)),
        "avg_view_duration_s": float(stats.get("averageViewDuration", 0)),
        "ctr": float(stats.get("ctr", 0)) / 100,  # API returns percent
        "impressions": int(stats.get("impressions", 0)),
        "retention_points": client.retention(args.youtube_id, start, end),
        "subs_gained": int(stats.get("subscribersGained", 0)),
        'availability':{'views':'ok' if 'views' in stats else 'unavailable','avg_view_duration_s':'ok' if 'averageViewDuration' in stats else 'unavailable','thumbnail_ctr':'reporting_route_required','thumbnail_impressions':'reporting_route_required'},
        'window_kind':'exact_rolling' if exact else 'source_calendar',
    }
    doc = load_or_new(args.video_id)
    record_window(doc, args.window, window, args.video_len_s, cfg)
    out = write_readback(doc)
    print(f"readback: {out} verdict={doc['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
