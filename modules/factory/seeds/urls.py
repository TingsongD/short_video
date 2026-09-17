"""Seed URL parsing (F09 checklist 1): canonicalize supported platform
URLs into (platform, canonical_url, native_id). Tracking parameters are
dropped by canonicalization, never conflating distinct posts. The
original URL and attribution are preserved on the Seed record."""
import re
from urllib.parse import urlsplit

from ...common.video_reference import canonical_video_url
from ..domain.errors import ContractError

_HOST_PLATFORM = {
    "youtu.be": "youtube",
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "m.youtube.com": "youtube",
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
}


def _instagram(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ContractError("unsupported_url", "url", url)
    m = re.fullmatch(r"/(reel|p)/([A-Za-z0-9_-]+)/?", parsed.path)
    if not m:
        raise ContractError("unsupported_url", "url", url)
    kind, native_id = m.groups()
    return f"https://www.instagram.com/{kind}/{native_id}", native_id


def parse_source_url(url):
    """→ {platform, canonical_url, native_id}. Raises ContractError for
    unsupported or malformed references."""
    if not isinstance(url, str) or not url.strip():
        raise ContractError("missing_url", "url", repr(url))
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        raise ContractError("unsupported_url", "url", url)
    platform = _HOST_PLATFORM.get(host.lower())
    if platform is None:
        raise ContractError("unsupported_platform", "url",
                            f"no adapter for host {host!r}")
    try:
        if platform == "instagram":
            canonical, native_id = _instagram(url)
        else:
            canonical, native_id = canonical_video_url(platform, url)
    except ValueError as e:
        raise ContractError("unsupported_url", "url", str(e))
    return {"platform": platform, "canonical_url": canonical,
            "native_id": native_id}
