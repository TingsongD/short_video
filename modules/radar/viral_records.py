"""Normalize provider evidence, then apply our own strict views/followers gate.

No profile enrichment calls, inferred dates, or inferred channel medians.
Unsupported/missing fields are retained as review reasons, never filled in.
"""
from datetime import datetime, timezone
import math

from modules.common.video_reference import canonical_video_url
from .metrics import followers_outlier
from .scanner import guess_format
from .viral_client import ViralError


def first(obj, *keys):
    return next((obj[k] for k in keys if obj.get(k) is not None), None)


def records(payload):
    if not isinstance(payload, dict):
        raise ViralError("Expected an object containing Viral Outliers posts")
    if payload.get("error") or payload.get("success") is False:
        raise ViralError("Viral Outliers returned an error instead of posts")
    # The free feed uses outliers. Paid schemas are loosely specified by the
    # provider; recognize explicit list envelopes, fail closed on other shapes.
    for key in ("outliers", "posts", "results", "items", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            if not all(isinstance(row, dict) for row in rows):
                raise ViralError("Viral Outliers returned malformed post records")
            return rows
        if key == "data" and isinstance(rows, dict):
            return records(rows)
    raise ViralError("Unrecognized Viral Outliers response shape; saved response needs review")


def count(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number >= 0 and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def published(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def normalize(row, now, thresholds):
    profile = first(row, "profile", "profiles", "social_profile") or {}
    if not isinstance(profile, dict):
        profile = {}
    platform = str(row.get("platform") or profile.get("platform") or "").lower()
    reasons = []
    source = first(row, "postLink", "post_link", "post_url", "postUrl", "url")
    try:
        source, native_id = canonical_video_url(platform, source)
    except ValueError:
        source, native_id = None, None
        reasons.append("missing_or_unsupported_video_url")
    views = count(first(row, "views", "view_count", "viewCount", "play_count", "playCount"))
    follower_keys = ("followerCount", "follower_count", "followers_count", "followers",
                     "subscriberCount", "subscriber_count", "subscribers")
    followers = count(first(row, *follower_keys))
    denominator_source = "post"
    if followers is None:
        followers = count(first(profile, *follower_keys))
        denominator_source = "profile"
    title = first(row, "title", "caption", "description")
    if not isinstance(title, str) or not title.strip():
        # A blank title often accompanies a populated caption.
        title = next((row[k] for k in ("caption", "description")
                      if isinstance(row.get(k), str) and row[k].strip()), "")
    pub = published(first(row, "published_at", "publishedAt", "posted_at", "postedAt",
                          "taken_at", "takenAt", "createTime"))
    handle = first(profile, "handle", "username") or first(row, "handle", "username")
    if platform == "tiktok" and source:
        handle = source.split("/@", 1)[1].split("/", 1)[0]
    creator = handle or first(profile, "channel_id", "channelId", "id") or row.get("channel_id")
    if not isinstance(creator, str) or not creator.strip():
        reasons.append("missing_creator")
        creator = ""
    creator_id = creator.lstrip("@").lower() if handle else creator
    if platform == "youtube":
        # Stable channel/profile IDs take precedence over changeable handles.
        stable_id = first(profile, "channel_id", "channelId") or row.get("channel_id") or profile.get("id")
        if isinstance(stable_id, str) and stable_id:
            creator_id = stable_id
    if platform not in thresholds.get("platforms", ["youtube", "tiktok"]):
        reasons.append("unselected_platform")
    if row.get("deleted_at") or row.get("deletedAt") or row.get("is_deleted") is True:
        reasons.append("deleted_post")
    if profile.get("is_active") is False or profile.get("isActive") is False or row.get("is_active") is False:
        reasons.append("inactive_profile")
    content_type = str(first(row, "contentType", "content_type", "type") or "").lower()
    if content_type not in ("video", "short", "shorts", "reel", "reels", "tiktok_video"):
        reasons.append("not_verified_video")
    if not title:
        reasons.append("missing_title")
    if pub is None:
        reasons.append("missing_publication_date")
    elif not 0 <= (now - pub).total_seconds() / 86400 <= thresholds["max_video_age_days"]:
        reasons.append("outside_age_window")
    if views is None:
        reasons.append("missing_views")
    if followers is None or followers <= 0:
        reasons.append("missing_positive_followers")
    ratio = views / followers if views is not None and followers else None
    ratio_pass = followers_outlier(views, followers, thresholds["breakout_subs_ratio"])
    if ratio is not None and not ratio_pass:
        reasons.append("views_to_followers_not_above_threshold")
    observation = {
        "provider": "viral-outliers", "provider_post_id": row.get("id"),
        "platform": platform, "source_url": source, "views": views,
        "followers": followers, "denominator_source": denominator_source,
        "views_to_followers": ratio, "ratio_pass": ratio_pass,
        "observed_at": now.isoformat(), "reasons": reasons,
    }
    if reasons:
        return None, observation
    # channel_avg and multiplier historically mean a measured channel median.
    # Zero remains the contract's unavailable sentinel; the explicit flag tells
    # downstream prompts not to interpret it as poor performance.
    video = {
        "video_id": native_id if platform == "youtube" else f"{platform}:{native_id}",
        "channel_id": f"{platform}:{creator_id}",
        "channel_title": str(first(profile, "display_name", "displayName") or creator),
        "title": title.strip(), "views": views, "followers": followers,
        "channel_avg": 0.0, "multiplier": 0.0, "baseline_available": False,
        "subs_ratio": ratio, "published_at": pub.isoformat().replace("+00:00", "Z"),
        "format_guess": guess_format(title), "platform": platform,
        "source_url": source, "provider": "viral-outliers",
        "provider_post_id": row.get("id"), "denominator_source": denominator_source,
        "observed_at": now.isoformat(),
        "provider_stats_updated_at": first(row, "stats_updated_at", "updated_at", "updatedAt"),
        "vendor_outlier_score": first(row, "outlierScore", "outlier_score"),
    }
    return video, observation
