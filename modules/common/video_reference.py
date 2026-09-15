"""Canonical public video references; never turn a TikTok ID into a YouTube URL."""
import re
from urllib.parse import parse_qs, urlsplit


def canonical_video_url(platform, url):
    if not isinstance(url, str):
        raise ValueError("Missing video reference URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("Expected a public HTTPS video reference")
    if platform == "tiktok" and parsed.hostname in ("www.tiktok.com", "tiktok.com"):
        match = re.fullmatch(r"/@([\w.-]+)/video/(\d+)/?", parsed.path)
        if match:
            handle, native_id = match.groups()
            return f"https://www.tiktok.com/@{handle.lower()}/video/{native_id}", native_id
    if platform == "youtube":
        native_id = None
        if parsed.hostname == "youtu.be":
            native_id = parsed.path.strip("/")
        elif parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                native_id = parse_qs(parsed.query).get("v", [None])[0]
            else:
                match = re.fullmatch(r"/shorts/([\w-]+)/?", parsed.path)
                native_id = match.group(1) if match else None
        if native_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", native_id):
            route = f"shorts/{native_id}" if "/shorts/" in parsed.path else f"watch?v={native_id}"
            return f"https://www.youtube.com/{route}", native_id
    raise ValueError("Unsupported platform or video reference URL")


def video_reference(video):
    platform = video.get("platform", "youtube")
    if video.get("source_url"):
        return canonical_video_url(platform, video["source_url"])[0]
    if platform != "youtube" or ":" in video["video_id"]:
        raise ValueError("A non-YouTube reference needs its original source_url")
    # Historical frozen fixtures use synthetic YouTube IDs.
    return f"https://www.youtube.com/watch?v={video['video_id']}"
