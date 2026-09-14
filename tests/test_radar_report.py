"""M1: end-to-end fixture scan -> schema-valid niche_report (test_report_schema).

Fake transport serves the frozen tests/fixtures/yt/* responses plus a few
inline extras (UCseed2/UCseed3 baselines, a second 'dark psychology' hit so
one cluster confirms). No network.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from modules.common.schema import validate
from modules.radar.client import YouTubeClient
from modules.radar.quota import QuotaManager
from modules.radar.report import build_report
from modules.radar.scanner import scan

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
THRESHOLDS = dict(
    json.loads("{}"),
    breakout_multiplier=5.0,
    breakout_subs_ratio=2.0,
    max_video_age_days=14,
    cluster_min_channels=2,
)

CHANNEL_STATS = json.loads((FIXTURES / "yt" / "channel_stats.json").read_text())["items"]
CHANNEL_VIDEOS = json.loads((FIXTURES / "yt" / "channel_videos.json").read_text())["items"]
SEARCH = json.loads((FIXTURES / "yt" / "search_response.json").read_text())["items"]

# inline extras (not frozen fixtures): UCseed2/UCseed3 baselines + 2 more hits
EXTRA_CHANNELS = [
    {"id": "UCseed3", "snippet": {"title": "Fixture Third Channel"},
     "statistics": {"subscriberCount": "2400", "videoCount": "9"}},
]
EXTRA_UPLOADS = {
    "UCseed2": [
        {"id": "uc2_a", "publishedAt": "2026-09-10T00:00:00Z", "viewCount": "800"},
        {"id": "uc2_b", "publishedAt": "2026-09-08T00:00:00Z", "viewCount": "900"},
        {"id": "uc2_c", "publishedAt": "2026-09-05T00:00:00Z", "viewCount": "1000"},
    ],
    "UCseed3": [
        {"id": "uc3_a", "publishedAt": "2026-09-10T00:00:00Z", "viewCount": "700"},
        {"id": "uc3_b", "publishedAt": "2026-09-07T00:00:00Z", "viewCount": "750"},
        {"id": "uc3_c", "publishedAt": "2026-09-03T00:00:00Z", "viewCount": "800"},
    ],
}
EXTRA_SEARCH_ITEMS = [
    {"id": {"videoId": "vid_search_3"},
     "snippet": {"title": "dark psychology signs you missed",
                 "channelId": "UCseed3", "publishedAt": "2026-09-12T10:00:00Z"}},
]
EXTRA_VIDEO_STATS = {
    "vid_search_1": ("UCseed1", "dark psychology trick that went viral",
                     "2026-09-12T09:00:00Z", "4800"),
    "vid_search_2": ("UCseed2", "the psychology fact nobody believes",
                     "2026-09-11T18:30:00Z", "5400"),
    "vid_search_3": ("UCseed3", "dark psychology signs you missed",
                     "2026-09-12T10:00:00Z", "6000"),
}


def _video_item(vid, channel_id, title, published, views):
    return {
        "id": vid,
        "snippet": {"title": title, "channelId": channel_id,
                    "channelTitle": f"ch-{channel_id}", "publishedAt": published},
        "statistics": {"viewCount": views},
    }


def _upload_items(channel_id):
    items = [
        {"id": v["id"], "publishedAt": v["snippet"]["publishedAt"]}
        for v in CHANNEL_VIDEOS
        if v["snippet"]["channelId"] == channel_id
    ]
    items += [{"id": e["id"], "publishedAt": e["publishedAt"]}
              for e in EXTRA_UPLOADS.get(channel_id, [])]
    return items


class FakeTransport:
    """Maps YouTube endpoints to fixture-shaped responses."""

    def __init__(self):
        self.calls = []

    def __call__(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        if endpoint == "search":
            return {"items": SEARCH + EXTRA_SEARCH_ITEMS}
        if endpoint == "channels":
            wanted = params.get("id", "").split(",") if params.get("id") else []
            items = []
            for c in CHANNEL_STATS + EXTRA_CHANNELS:
                if c["id"] in wanted:
                    item = dict(c)
                    item.setdefault("contentDetails", {})["relatedPlaylists"] = {
                        "uploads": f"UU{c['id']}"
                    }
                    items.append(item)
            return {"items": items}
        if endpoint == "playlistItems":
            channel_id = params["playlistId"][2:]
            return {"items": [
                {"contentDetails": {"videoId": u["id"]}}
                for u in _upload_items(channel_id)
            ]}
        if endpoint == "videos":
            wanted = set(params["id"].split(","))
            items = [v for v in CHANNEL_VIDEOS if v["id"] in wanted]
            for cid, ups in EXTRA_UPLOADS.items():
                items += [
                    _video_item(u["id"], cid, f"baseline {u['id']}",
                                u["publishedAt"], u["viewCount"])
                    for u in ups if u["id"] in wanted
                ]
            for vid, (cid, title, pub, views) in EXTRA_VIDEO_STATS.items():
                if vid in wanted:
                    items.append(_video_item(vid, cid, title, pub, views))
            return {"items": items}
        raise AssertionError(f"unexpected endpoint {endpoint}")


NICHES = [
    {"name": "psychology_facts",
     "keywords": ["psychology facts", "dark psychology"],
     "seed_channels": ["UCseed1", "UCseed2"]},
    {"name": "money_tips", "keywords": [], "seed_channels": []},
]


def run_scan(budget=10_000):
    transport = FakeTransport()
    client = YouTubeClient("fake-key", QuotaManager(budget), transport)
    result = scan(client, NICHES, THRESHOLDS, now=NOW)
    report = build_report(
        result["clusters"], result["scanned_at"],
        [n["name"] for n in NICHES], client.quota.used,
        degraded=result["degraded"],
    )
    return report, transport, result


def test_report_validates_against_frozen_schema():
    report, _, _ = run_scan()
    validate(report, "niche_report.schema.json")


def test_confirmed_cluster_two_channels_same_topic():
    report, _, _ = run_scan()
    confirmed = [n for n in report["niches"] if n["confirmed"]]
    assert len(confirmed) == 1
    ids = {v["video_id"] for v in confirmed[0]["breakout_videos"]}
    assert ids == {"vid_outlier_1", "vid_search_3"}
    assert confirmed[0]["cluster_size"] == 2


def test_outlier_metrics_in_report():
    report, _, _ = run_scan()
    all_vids = [v for n in report["niches"] for v in n["breakout_videos"]]
    outlier = next(v for v in all_vids if v["video_id"] == "vid_outlier_1")
    assert outlier["multiplier"] == 6.2
    assert outlier["subs_ratio"] == 3.1
    assert outlier["channel_avg"] == 1000.0


def test_old_video_and_subthreshold_hit_excluded():
    report, _, _ = run_scan()
    ids = {v["video_id"] for n in report["niches"] for v in n["breakout_videos"]}
    assert "vid_old_1" not in ids          # 25 days old
    assert "vid_search_1" not in ids       # 4800/1000 = 4.8x < 5.0


def test_quiet_niche_gets_empty_entry():
    report, _, _ = run_scan()
    money = next(n for n in report["niches"] if n["niche"] == "money_tips")
    assert money["cluster_size"] == 0 and not money["confirmed"]
    assert money["breakout_videos"] == []
