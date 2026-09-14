"""M9 upload lanes. Lane 1 default = manual checklist (docs/publish-manual.md).
upload_post() is the optional MPT cross-post path — injectable transport,
never called in tests."""
import json
import urllib.request


def manual_instructions(video_id, metadata, video_path):
    tags = " ".join(f"#{t}" for t in metadata["hashtags"])
    return f"""Manual publish checklist — {video_id}
1. Open YouTube Studio -> Create -> Upload video
2. File: {video_path}
3. Title: {metadata['title']}
4. Description: {metadata['caption']} {tags}
5. Audience: Not made for kids. Shorts feed: yes (9:16 detected automatically).
6. After publish, copy the video id and run:
   python -m modules.publish record {video_id} --youtube-id <ID>
"""


def upload_post(video_path, metadata, api_key, platforms=("youtube",),
                transport=None):
    """Optional upload-post.com cross-post. Returns platform->id map."""
    payload = {
        "video": str(video_path),
        "title": metadata["title"],
        "description": metadata["caption"],
        "platform": list(platforms),
    }
    post = transport or _http
    return post("https://api.upload-post.com/api/upload", payload, api_key)


def _http(url, payload, api_key):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Apikey {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())
