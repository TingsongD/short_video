"""M6 Pexels fallback: fetch a stock clip/photo when both lanes fail a shot.
Transport is injectable — unit tests never touch the network."""
import json
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.pexels.com"


class PexelsClient:
    def __init__(self, api_key, transport=None, downloader=None):
        self.api_key = api_key
        self.transport = transport or self._http_json
        self.downloader = downloader or self._download

    def _http_json(self, url):
        req = urllib.request.Request(
            url, headers={"Authorization": self.api_key}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def _download(self, url):
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()

    def search_video(self, term):
        url = f"{API}/videos/search?{urllib.parse.urlencode({'query': term, 'per_page': 1, 'orientation': 'portrait'})}"
        data = self.transport(url)
        vids = data.get("videos") or []
        if not vids:
            return None
        files = sorted(
            vids[0].get("video_files", []),
            key=lambda f: abs((f.get("height") or 0) - 1280),
        )
        return files[0]["link"] if files else None

    def search_photo(self, term):
        url = f"{API}/v1/search?{urllib.parse.urlencode({'query': term, 'per_page': 1, 'orientation': 'portrait'})}"
        data = self.transport(url)
        photos = data.get("photos") or []
        return photos[0]["src"]["large"] if photos else None

    def fetch(self, term, kind, out_path):
        """kind: 'video'|'image'. Returns True if a file was written."""
        url = self.search_video(term) if kind == "video" else self.search_photo(term)
        if not url:
            return False
        Path(out_path).write_bytes(self.downloader(url))
        return True
