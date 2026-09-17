"""Automated publication adapter (F31) — Upload Post boundary.

Corrects the legacy uploader defects:
- the video travels as multipart BYTES (`video` file field) or a
  documented accessible URL (`video_url`) — never a local path string;
- required `user` and `platform[]` fields are validated before send;
- a stable `Idempotency-Key` header + request identity make retries
  safe — a metadata `external_id` is NOT a dedup guarantee;
- submission is asynchronous: `upload` returns a request id that must
  be polled via `status` until a terminal state; `verify_post`
  confirms the actual public post on the platform side.

The transport is injectable: `transport(request) -> response` where
request = {"method","path","headers","fields","file"} and file =
{"name","filename","content_type","bytes"}. Tests use FakePublisher;
the live transport is `http_transport` below.
"""
import json
import uuid
from pathlib import Path

UPLOAD_PATH = "/api/upload"
STATUS_PATH = "/api/upload/status"
POSTS_PATH = "/api/posts"
DEFAULT_BASE = "https://api.upload-post.com"

TERMINAL = {"public", "failed", "draft", "scheduled"}
ACCEPTED = {"accepted", "queued", "uploading", "processing"}


class PublishTransportError(Exception):
    """Transport-level failure — the remote effect is UNKNOWN."""

    def __init__(self, message, status_code=0, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def http_transport(request):
    """Live transport: multipart/form-data over urllib. Never used in
    tests — inject FakePublisher.transport instead."""
    import urllib.request
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in request["fields"].items():
        if isinstance(value, (list, tuple)):
            for v in value:
                parts.append((name, v))
        else:
            parts.append((name, value))
    body = bytearray()
    for name, value in parts:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="{name}"\r\n\r\n{value}\r\n').encode()
    f = request.get("file")
    if f:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f'name="{f["name"]}"; filename="{f["filename"]}"\r\n'
                 f"Content-Type: {f['content_type']}\r\n\r\n").encode()
        body += f["bytes"] + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        request["base_url"] + request["path"], data=bytes(body),
        headers={**request["headers"],
                 "Content-Type":
                 f"multipart/form-data; boundary={boundary}"},
        method=request["method"])
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return {"status": r.status, "body": json.loads(r.read())}
    except urllib.error.HTTPError as e:
        raise PublishTransportError(
            f"http_{e.code}", status_code=e.code,
            body=e.read().decode("utf-8", "replace"))


class UploadPostPublisher:
    """Validated Upload Post client. `user` (the account profile the
    provider posts under) is mandatory; without it a request would be
    rejected after the file left the building."""

    def __init__(self, api_key="", user="", base_url=DEFAULT_BASE,
                 transport=None, policy=None):
        self.api_key = api_key
        self.user = user
        self.base_url = base_url
        from ..execution.policy import live_transport
        self.transport = transport or live_transport(http_transport, "publish", policy)

    # ------------------------------------------------------------- --

    def readiness(self):
        problems = []
        if not self.api_key:
            problems.append("missing_api_key")
        if not self.user:
            problems.append("missing_user")
        return {"provider": "upload_post", "configured": not problems,
                "problems": problems}

    def upload(self, *, video_path="", video_url="", title="",
               description="", platforms=(), visibility="public",
               schedule_date="", user="", idempotency_key="",
               extra_fields=None):
        """Submit the async upload request. Exactly one of video_path
        (bytes read and sent) or video_url (accessible to the provider)
        is required. Returns {"request_id", "status", ...}."""
        user = user or self.user
        if not user:
            raise ValueError("upload_post requires `user`")
        if not platforms:
            raise ValueError("upload_post requires `platform[]`")
        if not idempotency_key:
            raise ValueError("upload requires a stable idempotency_key")
        if bool(video_path) == bool(video_url):
            raise ValueError("exactly one of video_path|video_url")
        fields = {"user": user, "platform[]": list(platforms),
                  "title": title, "description": description,
                  "visibility": visibility}
        if schedule_date:
            fields["schedule_date"] = schedule_date
        for k, v in (extra_fields or {}).items():
            fields[k] = v
        file_field = None
        if video_path:
            data = Path(video_path).read_bytes()      # real bytes
            file_field = {"name": "video",
                          "filename": Path(video_path).name,
                          "content_type": "video/mp4", "bytes": data}
        else:
            fields["video_url"] = video_url
        resp = self.transport({
            "method": "POST", "path": UPLOAD_PATH,
            "base_url": self.base_url,
            "headers": {"Authorization": f"Apikey {self.api_key}",
                        "Idempotency-Key": idempotency_key},
            "fields": fields, "file": file_field})
        return self._normalise_upload(resp)

    def _normalise_upload(self, resp):
        body = resp.get("body") or {}
        rid = (body.get("request_id") or body.get("id")
               or body.get("job_id") or "")
        status = str(body.get("status") or "accepted").lower()
        if status not in TERMINAL | ACCEPTED:
            status = "accepted"
        out = {"request_id": rid, "status": status}
        for k in ("post_url", "remote_post_id", "scheduled_at",
                  "published_at", "visibility"):
            if body.get(k):
                out[k] = body[k]
        return out

    def status(self, request_id):
        """Poll async completion by provider request identity."""
        resp = self.transport({
            "method": "GET",
            "path": f"{STATUS_PATH}?request_id={request_id}",
            "base_url": self.base_url,
            "headers": {"Authorization": f"Apikey {self.api_key}"},
            "fields": {}, "file": None})
        body = resp.get("body") or {}
        out = {"request_id": request_id,
               "status": str(body.get("status") or "unknown").lower()}
        for k in ("post_url", "remote_post_id", "published_at",
                  "scheduled_at", "visibility", "error"):
            if body.get(k) is not None:
                out[k] = body[k]
        return out

    def find_by_idempotency_key(self, idempotency_key):
        """Recovery listing: did a request with this identity already
        land? Returns the normalised request or None."""
        resp = self.transport({
            "method": "GET",
            "path": f"{STATUS_PATH}?idempotency_key={idempotency_key}",
            "base_url": self.base_url,
            "headers": {"Authorization": f"Apikey {self.api_key}"},
            "fields": {}, "file": None})
        body = resp.get("body") or {}
        if not body or body.get("status") in (None, "not_found"):
            return None
        return self._normalise_upload({"body": body})

    def verify_post(self, post_ref):
        """Inspect the actual post — account, visibility and public
        availability — not just our request journal."""
        resp = self.transport({
            "method": "GET", "path": f"{POSTS_PATH}/{post_ref}",
            "base_url": self.base_url,
            "headers": {"Authorization": f"Apikey {self.api_key}"},
            "fields": {}, "file": None})
        body = resp.get("body") or {}
        if not body or body.get("status") == "not_found":
            return None
        return {"remote_post_id": body.get("id") or post_ref,
                "post_url": body.get("url", ""),
                "account_id": body.get("account", ""),
                "platform": body.get("platform", ""),
                "visibility": body.get("visibility", ""),
                "status": body.get("status", ""),
                "published_at": body.get("published_at", "")}

    def update_post(self, post_ref, fields):
        """Explicit metadata change on a live post — a separate
        authorised action, never bundled into publish/retry."""
        resp = self.transport({
            "method": "PATCH", "path": f"{POSTS_PATH}/{post_ref}",
            "base_url": self.base_url,
            "headers": {"Authorization": f"Apikey {self.api_key}"},
            "fields": dict(fields), "file": None})
        return resp.get("body") or {}

    def delete_post(self, post_ref):
        """Explicit deletion. Callers keep the durable record — the
        remote post is removed but history is not rewritten."""
        resp = self.transport({
            "method": "DELETE", "path": f"{POSTS_PATH}/{post_ref}",
            "base_url": self.base_url,
            "headers": {"Authorization": f"Apikey {self.api_key}"},
            "fields": {}, "file": None})
        return resp.get("body") or {}
