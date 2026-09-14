"""M10: window scheduling, verdict thresholds, readback schema, M3 feed
(test_windows, test_verdict, test_readback_schema, test_promotion_feed)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.analytics.pull import AnalyticsClient
from modules.analytics.readback import (
    load_or_new, record_window, weekly_summary, write_readback,
)
from modules.analytics.verdict import format_promotion_signal, verdict
from modules.analytics.windows import due_windows, next_due, pull_at
from modules.common.schema import validate
from modules.formats.promote import update_entry

CFG = {"windows_hours": [48, 168, 672], "win_views_multiplier": 2.0,
       "win_avd_ratio": 0.7}
RECORD = {
    "video_id": "v-20260914-001",
    "platform_video_ids": {"youtube": "dQw4w9WgXcQ"},
    "title": "t", "caption": "c", "hashtags": [],
    "published_at": "2026-09-14T15:00:00Z",
    "format_id": "fmt-dark-list-3", "idea_id": "idea-20260914-001",
    "niche": "psychology_facts", "variant_index": 1,
}
NOW = datetime(2026, 9, 16, 16, 0, tzinfo=timezone.utc)  # 49h after publish


def test_window_pull_times_timezone_safe():
    assert pull_at(RECORD["published_at"], 48) == datetime(
        2026, 9, 16, 15, 0, tzinfo=timezone.utc
    )


def test_due_windows_48h_only():
    due = due_windows(RECORD, {}, CFG["windows_hours"], now=NOW)
    assert due == ["48h"]
    # after recording 48h, nothing due until 7d
    assert due_windows(RECORD, {"48h": {}}, CFG["windows_hours"], now=NOW) == []


def test_next_due_points_at_7d():
    nxt = next_due(RECORD, {"48h": {}}, CFG["windows_hours"], now=NOW)
    assert nxt == datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
    assert next_due(RECORD, {"48h": {}, "7d": {}, "28d": {}},
                    CFG["windows_hours"], now=NOW) is None


def test_verdict_thresholds():
    w_win = {"views": 2400, "avg_view_duration_s": 18.5}
    assert verdict(w_win, 25.0, 1000, CFG) == "win"      # 2.4x, 74% avd
    assert verdict({"views": 1900, "avg_view_duration_s": 20}, 25, 1000, CFG) == "loss"
    assert verdict({"views": 2400, "avg_view_duration_s": 10}, 25, 1000, CFG) == "loss"
    assert verdict(None, 25, 1000, CFG) == "pending"


def test_readback_schema_after_window_merge(tmp_path):
    doc = load_or_new("v-20260914-001", directory=tmp_path)
    doc["baseline_median_views"] = 1000.0
    window = {
        "pulled_at": "2026-09-16T15:00:00Z", "views": 2400,
        "avg_view_duration_s": 18.5, "ctr": 0.062, "impressions": 38500,
        "retention_points": [{"t_ratio": 0.0, "audience_ratio": 1.0}],
        "subs_gained": 12,
    }
    record_window(doc, "48h", window, video_len_s=25.0, cfg=CFG)
    assert doc["verdict"] == "win" and doc["format_promotion"] == "promote"
    p = write_readback(doc, directory=tmp_path)
    validate(json.loads(p.read_text()), "readback.schema.json")


def test_verdict_feeds_format_promotion(tmp_path):
    """A win verdict + enough videos -> M3 flips candidate to proven."""
    entry = {"format_id": "fmt-x", "status": "candidate",
             "our_stats": {"videos": 2, "wins": 2, "avg_multiplier": 2.0}}
    doc = load_or_new("v-9", directory=tmp_path)
    doc["baseline_median_views"] = 1000.0
    record_window(doc, "48h", {"pulled_at": "2026-09-16T00:00:00Z",
                             "views": 3000, "avg_view_duration_s": 20},
                  video_len_s=25.0, cfg=CFG)
    cfg_f = {"promote_min_videos": 3, "promote_min_multiplier": 1.5,
             "retire_consecutive_losses": 3}
    entry, changed = update_entry(entry, doc, cfg_f)
    assert changed and entry["status"] == "proven"


def test_weekly_summary_lists_verdicts(tmp_path):
    doc = load_or_new("v-1", directory=tmp_path)
    doc["verdict"] = "win"
    write_readback(doc, directory=tmp_path)
    text = weekly_summary([doc])
    assert "v-1" in text and "win" in text


def test_pull_client_parses_analytics_rows():
    def fake(url):
        if "elapsedVideoTimeRatio" in url:
            return {"rows": [[0.0, 1.0], [0.5, 0.55], [1.0, 0.36]]}
        return {"columnHeaders": [
            {"name": "views"}, {"name": "averageViewDuration"},
            {"name": "impressions"}, {"name": "ctr"},
            {"name": "subscribersGained"}],
            "rows": [[2400, 18.5, 38500, 6.2, 12]]}

    c = AnalyticsClient(transport=fake)
    rows = c.analytics_rows("yt1", "2026-09-14", "2026-09-16")
    assert rows["views"] == 2400 and rows["averageViewDuration"] == 18.5
    pts = c.retention("yt1", "2026-09-14", "2026-09-16")
    assert pts[0] == {"t_ratio": 0.0, "audience_ratio": 1.0}
