"""Niche scan orchestration. Per niche:

1. Resolve seed channels (handles via channels.list?forHandle, ids batched).
2. Pull each channel's recent uploads (playlistItems -> videos.list) and build
   the in-window median baseline.
3. Keyword searches (search.list, publishedAfter=max_video_age_days) — the
   expensive calls. On QuotaExhausted the scan degrades to channel-only data.
4. Batch-resolve channels discovered via search so their hits get real
   baseline/subs context.
5. Apply the configured eligibility rule and age window. The current followers
   mode uses strict views/followers > 2; historical median mode is retained.

Returns cluster dicts: {niche, topic, confirmed, videos:[contract-shaped]}.
"""
from datetime import datetime, timedelta, timezone

from .cluster import cluster_confirmed, group_clusters
from .metrics import channel_median, is_breakout, multiplier, subs_ratio
from .quota import QuotaExhausted

PARTS_CHANNEL = "snippet,statistics,contentDetails"
PARTS_VIDEO = "snippet,statistics"
MAX_DISCOVERED_CHANNELS = 10
BASELINE_POOL_SIZE = 25


def _parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _int(x):
    return int(x or 0)


def _age_days(published_at, now):
    return (now - _parse_dt(published_at)).total_seconds() / 86400.0


def resolve_seed_channels(client, seeds):
    """seeds: mix of @handles and UC... ids. Returns list of channel items."""
    items = []
    ids = [s.lstrip("@") for s in seeds if not s.startswith("@")]
    handles = [s for s in seeds if s.startswith("@")]
    if ids:
        data = client.api_get("channels", part=PARTS_CHANNEL, id=",".join(ids))
        items.extend(data.get("items", []))
    for h in handles:
        data = client.api_get("channels", part=PARTS_CHANNEL, forHandle=h)
        items.extend(data.get("items", []))
    return items


def get_channel_items(client, channel_ids):
    if not channel_ids:
        return []
    data = client.api_get(
        "channels", part=PARTS_CHANNEL, id=",".join(channel_ids)
    )
    return data.get("items", [])


def recent_videos(client, channel_item, max_items=BASELINE_POOL_SIZE):
    uploads = (
        channel_item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads:
        return []
    data = client.api_get(
        "playlistItems",
        part="contentDetails",
        playlistId=uploads,
        maxResults=min(max_items, 50),
    )
    ids = [
        it["contentDetails"]["videoId"]
        for it in data.get("items", [])
        if it.get("contentDetails", {}).get("videoId")
    ][:max_items]
    if not ids:
        return []
    data = client.api_get("videos", part=PARTS_VIDEO, id=",".join(ids))
    return data.get("items", [])


def search_keyword(client, keyword, published_after):
    data = client.api_get(
        "search",
        part="snippet",
        q=keyword,
        type="video",
        order="viewCount",
        maxResults=25,
        publishedAfter=published_after,
    )
    return data.get("items", [])


def video_stats(client, video_ids):
    if not video_ids:
        return {}
    items = client.api_get("videos", part=PARTS_VIDEO, id=",".join(video_ids))
    return {v["id"]: v for v in items.get("items", [])}


def _subs(channel_item):
    return _int(channel_item.get("statistics", {}).get("subscriberCount"))


def _in_window_views(videos, now, max_age_days):
    return [
        _int(v.get("statistics", {}).get("viewCount"))
        for v in videos
        if _age_days(v["snippet"]["publishedAt"], now) <= max_age_days
    ]


def _breakout_entry(video, baseline, subscribers, now, thresholds):
    stats = video.get("statistics", {})
    views = _int(stats.get("viewCount"))
    age = _age_days(video["snippet"]["publishedAt"], now)
    if not is_breakout(
        views=views,
        baseline=baseline,
        subscribers=subscribers,
        age_days=age,
        thresholds=thresholds,
    ):
        return None
    return {
        "video_id": video["id"],
        "channel_id": video["snippet"]["channelId"],
        "channel_title": video["snippet"].get("channelTitle", ""),
        "title": video["snippet"]["title"],
        "views": views,
        "channel_avg": baseline,
        "multiplier": multiplier(views, baseline),
        "subs_ratio": (views / subscribers if thresholds.get("eligibility") == "followers"
                       else subs_ratio(views, subscribers)),
        "followers": subscribers,
        "baseline_available": baseline > 0,
        "platform": "youtube",
        "published_at": video["snippet"]["publishedAt"],
        "format_guess": guess_format(video["snippet"]["title"]),
    }


def guess_format(title):
    t = title.lower()
    if any(c.isdigit() for c in t) or "top " in t:
        return "listicle"
    if "how to" in t or "tutorial" in t:
        return "tutorial"
    if "story" in t or "i tried" in t:
        return "story"
    if " vs" in t or "versus" in t:
        return "versus"
    if "?" in t:
        return "question"
    return "fact_drop"


def scan_niche(client, niche, thresholds, now, state):
    """state: mutable {'degraded': bool}. Returns list of cluster dicts."""
    max_age = thresholds["max_video_age_days"]
    published_after = (
        (now - timedelta(days=max_age)).isoformat().replace("+00:00", "Z")
    )

    try:
        channels = {c["id"]: c for c in resolve_seed_channels(client, niche.get("seed_channels", []))}
    except QuotaExhausted:
        state["degraded"] = True
        channels = {}

    channel_videos = {}
    for cid, ch in channels.items():
        try:
            channel_videos[cid] = recent_videos(client, ch)
        except QuotaExhausted:
            state["degraded"] = True
            channel_videos[cid] = []

    hits = []
    if not state["degraded"]:
        for kw in niche.get("keywords", []):
            try:
                hits.extend(search_keyword(client, kw, published_after))
            except QuotaExhausted:
                state["degraded"] = True
                break

    discovered_ids = []
    for h in hits:
        cid = h.get("snippet", {}).get("channelId")
        if cid and cid not in channels and cid not in discovered_ids:
            discovered_ids.append(cid)
    discovered_ids = discovered_ids[:MAX_DISCOVERED_CHANNELS]
    if discovered_ids and not state["degraded"]:
        try:
            for c in get_channel_items(client, discovered_ids):
                channels[c["id"]] = c
        except QuotaExhausted:
            state["degraded"] = True

    baselines = {}
    for cid, ch in channels.items():
        if cid not in channel_videos:
            try:
                channel_videos[cid] = recent_videos(client, ch)
            except QuotaExhausted:
                state["degraded"] = True
                channel_videos[cid] = []
        baselines[cid] = {
            "subs": _subs(ch),
            "in_window_views": _in_window_views(
                channel_videos[cid], now, max_age
            ),
        }

    hit_ids = [
        h["id"]["videoId"]
        for h in hits
        if h.get("id", {}).get("videoId")
    ]
    known_ids = {
        v["id"] for vids in channel_videos.values() for v in vids
    }
    missing = [i for i in dict.fromkeys(hit_ids) if i not in known_ids]
    try:
        extra = video_stats(client, missing)
    except QuotaExhausted:
        state["degraded"] = True
        extra = {}

    candidates = []
    for vids in channel_videos.values():
        candidates.extend(v for v in vids if _age_days(v["snippet"]["publishedAt"], now) <= max_age)
    candidates.extend(extra.values())

    seen, breakouts = set(), []
    for v in candidates:
        vid = v.get("id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        cid = v["snippet"]["channelId"]
        ctx = baselines.get(cid)
        if not ctx:
            continue
        # baseline = median of the channel's OTHER in-window videos
        pool = list(ctx["in_window_views"])
        own = _int(v.get("statistics", {}).get("viewCount"))
        if own in pool:
            pool.remove(own)
        baseline = channel_median(pool)
        entry = _breakout_entry(v, baseline, ctx["subs"], now, thresholds)
        if entry:
            breakouts.append(entry)

    groups = group_clusters(breakouts, niche.get("keywords", []))
    return [
        {
            "niche": niche["name"],
            "topic": topic,
            "confirmed": cluster_confirmed(vids, thresholds["cluster_min_channels"]),
            "videos": sorted(vids, key=lambda x: -x["multiplier"]),
        }
        for topic, vids in sorted(groups.items())
    ]


def scan(client, niches, thresholds, now=None):
    now = now or datetime.now(timezone.utc)
    state = {"degraded": False}
    clusters = []
    for niche in niches:
        clusters.extend(scan_niche(client, niche, thresholds, now, state))
    scanned_names = {n["name"] for n in niches}
    for name in scanned_names - {c["niche"] for c in clusters}:
        clusters.append(
            {"niche": name, "topic": None, "confirmed": False, "videos": []}
        )
    return {"clusters": clusters, "degraded": state["degraded"], "scanned_at": now}
