"""M1: cluster confirmation (BUILD_PLAN test_cluster)."""
from modules.radar.cluster import cluster_confirmed, group_clusters, topic_key

KEYWORDS = ["dark psychology", "psychology facts", "human behavior facts"]


def _vid(vid, channel, title):
    return {
        "video_id": vid, "channel_id": channel, "title": title,
        "views": 5000, "channel_avg": 1000.0, "multiplier": 5.0,
        "subs_ratio": 2.5, "published_at": "2026-09-12T00:00:00Z",
    }


def test_two_channels_same_topic_confirmed():
    vids = [
        _vid("v1", "UCa", "dark psychology trick that went viral"),
        _vid("v2", "UCb", "dark psychology secrets nobody shares"),
    ]
    groups = group_clusters(vids, KEYWORDS)
    assert len(groups) == 1
    assert cluster_confirmed(next(iter(groups.values())), 2)


def test_same_channel_twice_not_confirmed():
    vids = [
        _vid("v1", "UCa", "dark psychology trick"),
        _vid("v2", "UCa", "dark psychology secrets"),
    ]
    groups = group_clusters(vids, KEYWORDS)
    assert len(groups) == 1
    assert not cluster_confirmed(next(iter(groups.values())), 2)


def test_two_channels_different_topics_not_confirmed():
    vids = [
        _vid("v1", "UCa", "dark psychology trick"),
        _vid("v2", "UCb", "index fund compounding basics"),
    ]
    groups = group_clusters(vids, KEYWORDS)
    assert len(groups) == 2
    assert all(not cluster_confirmed(g, 2) for g in groups.values())


def test_topic_key_falls_back_when_no_keyword_match():
    key = topic_key("index fund compounding basics", KEYWORDS)
    assert key.startswith("misc:")
    assert key != "misc:"
