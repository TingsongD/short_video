"""M1: breakout flag on fixture channel (BUILD_PLAN test_breakout_flag).

Fixture UCseed1 in-window views: 900, 950, 1000, 1050, 1100 + outlier 6200.
Baseline for the outlier (own views excluded) = median(900..1100) = 1000
=> multiplier 6.2, subs_ratio 6200/2000 = 3.1, age 3d => FLAGGED.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.radar.metrics import channel_median, is_breakout, multiplier

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
THRESHOLDS = {
    "breakout_multiplier": 5.0,
    "breakout_subs_ratio": 2.0,
    "max_video_age_days": 14,
}


def _fixture_videos():
    data = json.loads((FIXTURES / "yt" / "channel_videos.json").read_text())
    return data["items"]


def _age(item):
    pub = datetime.fromisoformat(
        item["snippet"]["publishedAt"].replace("Z", "+00:00")
    )
    return (NOW - pub).total_seconds() / 86400.0


def _baseline_pool(exclude_id):
    return [
        int(v["statistics"]["viewCount"])
        for v in _fixture_videos()
        if v["id"] != exclude_id and _age(v) <= THRESHOLDS["max_video_age_days"]
    ]


def test_seeded_outlier_flagged():
    pool = _baseline_pool("vid_outlier_1")
    baseline = channel_median(pool)
    assert baseline == 1000.0
    assert multiplier(6200, baseline) == 6.2
    assert is_breakout(
        views=6200, baseline=baseline, subscribers=2000,
        age_days=_age(next(v for v in _fixture_videos() if v["id"] == "vid_outlier_1")),
        thresholds=THRESHOLDS,
    )


def test_below_multiplier_threshold_not_flagged():
    assert not is_breakout(
        views=4900, baseline=1000, subscribers=2000, age_days=3,
        thresholds=THRESHOLDS,
    )


def test_old_video_excluded_by_age():
    old = next(v for v in _fixture_videos() if v["id"] == "vid_old_1")
    assert _age(old) > 14
    assert not is_breakout(
        views=9000, baseline=1000, subscribers=2000,
        age_days=_age(old), thresholds=THRESHOLDS,
    )


def test_zero_view_video_not_flagged():
    assert not is_breakout(
        views=0, baseline=0, subscribers=2000, age_days=2,
        thresholds=THRESHOLDS,
    )
