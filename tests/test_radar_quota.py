"""M1: quota budget counter + graceful degradation (BUILD_PLAN test_quota)."""
import pytest

from modules.radar.client import YouTubeClient
from modules.radar.quota import COSTS, QuotaExhausted, QuotaManager

from test_radar_report import NICHES, THRESHOLDS, NOW, FakeTransport
from modules.radar.report import build_report
from modules.radar.scanner import scan


def test_search_costs_100_units():
    q = QuotaManager(1000)
    q.charge("search")
    assert q.used == 100
    q.charge("videos")
    assert q.used == 101


def test_budget_cap_blocks_calls():
    q = QuotaManager(150)
    q.charge("search")
    assert not q.can_afford("search")
    with pytest.raises(QuotaExhausted):
        q.charge("search")
    assert q.can_afford("videos")
    q.charge("videos")
    assert q.used == 101


def test_scan_degrades_to_channel_only_when_search_unaffordable():
    # budget: seeds(1) + 2x playlistItems(1) + 2x videos(1) = 5; +1 search = 105
    transport = FakeTransport()
    client = YouTubeClient("fake-key", QuotaManager(105), transport)
    result = scan(client, NICHES, THRESHOLDS, now=NOW)
    searches = [c for c in transport.calls if c[0] == "search"]
    assert len(searches) == 1          # second keyword never fired
    assert result["degraded"] is True
    report = build_report(
        result["clusters"], result["scanned_at"],
        [n["name"] for n in NICHES], client.quota.used, degraded=True,
    )
    ids = {v["video_id"] for n in report["niches"] for v in n["breakout_videos"]}
    assert "vid_outlier_1" in ids      # channel scan still produced data
