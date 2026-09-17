"""Verified Viral Outliers search route with durable synchronous receipts."""
import json
from datetime import datetime, timezone
from ...radar.viral_client import ViralOutliersClient, SEARCH_PATH
from ...radar.viral_records import records, first, count, published
from ..providers.synchronous import SynchronousAdapter
from ..execution.context import current_effect
from ..testing.fakes import ProviderError
from .http import BoundedHTTP


class ViralOutliersSearch(SynchronousAdapter):
    def __init__(self, state_dir, client, account):
        super().__init__(state_dir)
        self.client, self.account = client, account

    def execute(self, request):
        body = {"query": request["query"], "platforms": request.get("platforms") or ["youtube", "tiktok"],
                "timeFrame": request.get("time_frame") or "one_month", "sortBy": request.get("sort_by") or "views_desc",
                "page": request["page"], "pageSize": request["page_size"]}
        status, headers, payload = self.client.request("POST", SEARCH_PATH, body)
        if status == 402:
            raise ProviderError("insufficient_credits", http_status=402)
        if not 200 <= status < 300:
            raise ProviderError("research_http_error", http_status=status)
        now = datetime.now(timezone.utc).isoformat()
        posts = []
        for item in records(payload):
            profile = first(item, "profile", "profiles", "social_profile") or {}
            platform = (item.get("platform") or profile.get("platform") or "").lower()
            date = published(first(item, "published_at", "publishedAt", "postedAt", "posted_at"))
            posts.append({"post_id": first(item, "id", "post_id"), "platform": platform,
                "creator_id": first(profile, "channel_id", "channelId", "id", "handle", "username"),
                "views": count(first(item, "views", "view_count", "viewCount")),
                "followers": count(first(profile, "followerCount", "followers", "subscriberCount")),
                "provider_score": first(item, "outlierScore", "outlier_score"),
                "format": first(item, "contentType", "content_type"),
                "published_at": date.isoformat() if date else None, "observed_at": now,
                "url": first(item, "postLink", "post_link", "post_url", "url"),
                "title": first(item, "title", "caption", "description") or ""})
        actual = headers.get("x-credits-charged")
        return {"posts": posts}, None, {"actual_credits": int(actual) if actual is not None else None}


def configured_research(state_dir, account, credentials, policy):
    http = BoundedHTTP("viral_outliers", policy, 16 * 1024 * 1024)
    def transport(method, path, body):
        binding = current_effect.get()
        if not binding or binding["provider"] != "viral_outliers" or binding["account"] != account:
            raise ProviderError("authority_required")
        token = credentials()["VIRAL_OUTLIERS_API_KEY"]
        status, headers, raw = http(method, "https://viraloutliers.com" + path,
            json.dumps(body).encode() if body is not None else None,
            {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        return status, headers, json.loads(raw)
    return ViralOutliersSearch(state_dir, ViralOutliersClient(transport=transport), account)
