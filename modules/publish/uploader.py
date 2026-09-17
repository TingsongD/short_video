"""M9 upload lanes. Lane 1 default = manual checklist (docs/publish-manual.md).
upload_post() is the optional MPT cross-post path — now routed through
the validated F31 adapter (real bytes, required `user`, `platform[]`,
`Idempotency-Key`); injectable transport, never called in tests."""
import hashlib
from pathlib import Path


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
                user="", idempotency_key="", transport=None):
    """Optional upload-post.com cross-post. Returns the normalised
    upload response including the async `request_id` — completion must
    be observed via the status route, not assumed."""
    from modules.factory.integrations.publisher import \
        UploadPostPublisher
    if not user:
        raise ValueError(
            "upload_post requires `user` (the provider account "
            "profile) — set UPLOAD_POST_USER in secrets.toml or use "
            "the manual lane")
    if not idempotency_key:
        idempotency_key = hashlib.sha256(
            f"{Path(video_path).resolve()}|"
            f"{Path(video_path).stat().st_size}|"
            f"{metadata['title']}".encode()).hexdigest()[:32]
    client = UploadPostPublisher(api_key=api_key, user=user,
                                 transport=transport)
    return client.upload(
        video_path=str(video_path), title=metadata["title"],
        description=metadata["caption"], platforms=platforms,
        idempotency_key=idempotency_key,
        extra_fields={"hashtags": ",".join(metadata.get("hashtags", []))})
