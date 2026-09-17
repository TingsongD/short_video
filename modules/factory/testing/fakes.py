"""Fake remote providers with durable effects (F01).

State persists under <workspace>/fake_remote/<provider>.json — deliberately
independent of the application database — so "worker crashed after the
provider accepted" is a real condition, not a status edit.

Counters record billable submissions, polls, downloads, uploads and
publishes. Fault scripts from qa.faults modify behavior at named points;
an accepted operation retains its identity and reservation semantics.
"""
import hashlib
import json
from pathlib import Path


class ProviderError(RuntimeError):
    """Typed provider failure. `code` is stable; `transient` marks reads/
    transfers that may retry without implying a new paid effect."""
    def __init__(self, code, transient=False, http_status=None):
        self.code, self.transient, self.http_status = code, transient, http_status
        super().__init__(f"{code}")


class _LostResponse(ProviderError):
    """The remote effect may have happened; the caller never learned."""
    def __init__(self):
        super().__init__("response_lost", transient=True)


def _write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True))
    tmp.replace(path)


class FakeProviderState:
    """Load/save the provider's world: operations, uploads, publications."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {"operations": {}, "uploads": {}, "publications": {},
                        "counters": {"submit": 0, "poll": 0, "download": 0,
                                     "charge": 0, "upload": 0, "publish": 0},
                        "charges": [], "seq": 0, "authenticated": True,
                        "quota_reject": False}

    def save(self):
        _write_json(self.path, self.doc)

    def bump(self, counter):
        self.doc["counters"][counter] += 1


class FakeProvider:
    """Generic fake video/TTS/upload/publish effect provider.

    request -> operation lifecycle: accepted -> (poll) -> succeeded/failed;
    succeeded -> download -> bytes. Faults script deviations by name.
    """

    def __init__(self, name, state_dir, ids, clock, unit="usd_micros"):
        self.name = name
        self.unit = unit
        self.ids = ids
        self.clock = clock
        self.state = FakeProviderState(Path(state_dir) / f"{name}.json")
        self._lost_ids = set()   # ops whose ack was deliberately dropped

    # -- helpers ---------------------------------------------------------
    def _next_seq(self):
        self.state.doc["seq"] += 1
        return self.state.doc["seq"]

    def _check_auth(self):
        if not self.state.doc["authenticated"]:
            raise ProviderError("auth_required")

    def reconnect(self):
        self.state.doc["authenticated"] = True
        self.state.save()

    def expire_auth(self):
        self.state.doc["authenticated"] = False
        self.state.save()

    # -- generation-shaped effects --------------------------------------
    def submit(self, request, faults=(), price=None):
        """Persist a billable remote operation and return its receipt.

        `request` is hashed canonically; `price` is a typed amount dict like
        {"unit": "jimeng_credits", "amount": 54}. Returns the operation dict.
        """
        self._check_auth()
        body = json.dumps(request, sort_keys=True, default=str)
        request_hash = hashlib.sha256(body.encode()).hexdigest()

        if "reject-before-accept" in faults:
            raise ProviderError("rejected_before_accept")
        if "quota-rejection" in faults or self.state.doc["quota_reject"]:
            raise ProviderError("quota_exceeded", http_status=429)

        seq = self._next_seq()
        op_id = self.ids.next(f"{self.name}-op")
        op = {"operation_id": op_id, "seq": seq, "provider": self.name,
              "request_hash": request_hash, "status": "accepted",
              "faults": list(faults), "submitted_at": self.clock.iso(),
              "price": price, "polls": 0, "result": None}
        self.state.doc["operations"][op_id] = op
        self.state.bump("submit")
        if price:
            self.state.doc["charges"].append(
                {"operation_id": op_id, "unit": price["unit"],
                 "amount": price["amount"], "at": self.clock.iso()})
            self.state.bump("charge")
        if "accepted-then-failed" in faults:
            op["status"] = "failed"
            op["result"] = {"error": {"code": "generation_failed"}}
        self.state.save()

        if "malformed-ack" in faults:
            return "<<not-json"
        if "accept-then-timeout" in faults:
            self._lost_ids.add(op_id)
            raise _LostResponse()
        return dict(op)

    def poll(self, operation_id):
        self._check_auth()
        self.state.bump("poll")
        op = self.state.doc["operations"].get(operation_id)
        if op is None:
            self.state.save()
            raise ProviderError("operation_not_found")
        op["polls"] += 1
        if op["status"] == "cancel_requested":
            op["status"] = "cancelled"
        elif op["status"] == "accepted":
            if "stalled-operation" in op["faults"]:
                pass  # stays accepted forever
            elif "accepted-then-failed" in op["faults"]:
                op["status"] = "failed"
                op["result"] = {"error": {"code": "generation_failed"}}
            else:
                op["status"] = "succeeded"
                payload = f"fake-media:{self.name}:{operation_id}".encode()
                op["result"] = {
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_count": len(payload),
                    "finished_at": self.clock.iso(),
                    "usage": op.get("price")}
        self.state.save()
        return dict(op)

    def download(self, operation_id, destination=None):
        self._check_auth()
        op = self.state.doc["operations"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        if op["status"] != "succeeded":
            raise ProviderError("output_not_available")
        if "download-failure" in op["faults"]:
            self.state.bump("download")
            self.state.save()
            raise ProviderError("download_transport_failed", transient=True)
        self.state.bump("download")
        self.state.save()
        payload = f"fake-media:{self.name}:{operation_id}".encode()
        if "corrupt-bytes" in op["faults"]:
            payload = b"garbage-not-media"
        if destination is not None:
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        return {"operation_id": operation_id, "bytes": payload,
                "sha256": hashlib.sha256(payload).hexdigest()}

    def cancel(self, operation_id):
        """Acknowledgement is not terminal cancellation: an accepted op
        becomes cancel_requested and resolves to cancelled on next poll."""
        self._check_auth()
        op = self.state.doc["operations"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        if op["status"] in ("accepted", "running"):
            op["status"] = "cancel_requested"
        self.state.save()
        return {"operation_id": operation_id,
                "acknowledged": True, "terminal": False}

    def reconcile(self, operation_id=None, request_hash=None):
        """Truthful remote state for recovery — no new effects."""
        for op in self.state.doc["operations"].values():
            if operation_id and op["operation_id"] == operation_id:
                return dict(op)
            if request_hash and op["request_hash"] == request_hash:
                return dict(op)
        return None

    # -- upload-shaped effects (fake Drive) ------------------------------
    def upload(self, name, content, folder="root", faults=()):
        self._check_auth()
        digest = hashlib.sha256(content).hexdigest()
        file_id = self.ids.next(f"{self.name}-file")
        self.state.doc["uploads"][file_id] = {
            "file_id": file_id, "name": name, "folder": folder,
            "size": len(content), "md5": hashlib.md5(content).hexdigest(),
            "sha256": digest, "uploaded_at": self.clock.iso()}
        self.state.bump("upload")
        self.state.save()
        if "duplicate-upload" in faults or "lost-upload-ack" in faults:
            raise _LostResponse()
        return self.state.doc["uploads"][file_id]

    def find_upload(self, name=None, sha256=None):
        for up in self.state.doc["uploads"].values():
            if name is not None and up["name"] != name:
                continue
            if sha256 is not None and up["sha256"] != sha256:
                continue
            return dict(up)
        return None

    # -- publish-shaped effects ------------------------------------------
    def publish(self, request, faults=()):
        self._check_auth()
        post_id = self.ids.next(f"{self.name}-post")
        pub = {"post_id": post_id, "request": request,
               "status": "public" if "draft-only" not in faults else "draft",
               "published_at": self.clock.iso()}
        self.state.doc["publications"][post_id] = pub
        self.state.bump("publish")
        self.state.save()
        if "ambiguous-publish" in faults:
            raise _LostResponse()
        return dict(pub)

    # -- introspection ----------------------------------------------------
    def effect_counts(self):
        return dict(self.state.doc["counters"])

    def operation(self, operation_id):
        op = self.state.doc["operations"].get(operation_id)
        return dict(op) if op else None


# ---------------------------------------------------------------------
# Seed/source acquisition fake (F09)

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082")


class FakeSeedSource:
    """Scriptable source-acquisition provider: metadata lookups and
    media downloads behind the provider protocol (submit/poll/download/
    cancel/reconcile) so the F07 executor drives it.

    Posts persist in fake_remote state — restart-safe. `media_dir`
    holds real fixture bytes named `<post_id>.bin`; a post can instead
    declare media="image" (thumbnail bytes), "missing", an expired URL
    (refresh_url fixes it), or interrupt_downloads=N transient cuts.
    """

    def __init__(self, name, state_dir, ids, clock, media_dir=None):
        self.name = name
        self.ids = ids
        self.clock = clock
        self.media_dir = Path(media_dir) if media_dir else None
        self.state = FakeProviderState(Path(state_dir) / f"{name}.json")
        self.state.doc.setdefault("posts", {})
        self.state.doc.setdefault("refreshes", 0)
        self.state.doc.setdefault("source_ops", {})
        self.state.save()

    # -- setup -----------------------------------------------------------
    def register_post(self, post_id, **kw):
        post = {"post_id": post_id, "platform": "youtube",
                "native_id": post_id, "title": "", "creator_id": "",
                "stats": {}, "media": "missing", "url_state": "fresh",
                "interrupt_downloads": 0, "downloads_interrupted": 0}
        post.update(kw)
        post.setdefault(
            "media_url",
            f"https://cdn.fake/{post_id}/media?sig=fakesig{post_id}")
        self.state.doc["posts"][post_id] = post
        self.state.save()
        return post

    def post(self, post_id):
        return self.state.doc["posts"].get(post_id)

    # -- provider protocol -------------------------------------------------
    def submit(self, request):
        self.state.bump("submit")
        kind = request.get("kind")
        post = self.state.doc["posts"].get(request.get("post_id"))
        if post is None:
            raise ProviderError("post_unavailable", http_status=404)
        op_id = f"{self.name}-op:{self._next_seq()}"
        if kind == "metadata":
            result = {"title": post["title"], "creator_id": post["creator_id"],
                      "stats": post["stats"], "media_url": post["media_url"],
                      "post_id": post["post_id"]}
            op = {"operation_id": op_id, "status": "succeeded",
                  "result": result, "request": request}
        elif kind == "media":
            if post["url_state"] == "expired":
                raise ProviderError("expired_source", http_status=410)
            if post["media"] == "missing":
                raise ProviderError("media_unavailable", http_status=404)
            op = {"operation_id": op_id, "status": "accepted",
                  "request": request}
        else:
            raise ProviderError("unsupported_kind")
        self.state.doc["source_ops"][op_id] = op
        self.state.save()
        return {k: v for k, v in op.items() if k != "request"}

    def poll(self, operation_id):
        self.state.bump("poll")
        op = self.state.doc["source_ops"].get(operation_id)
        if op is None:
            raise ProviderError("unknown_operation", http_status=404)
        if op["status"] == "accepted":
            post = self.state.doc["posts"][op["request"]["post_id"]]
            if post["media"] == "missing":
                op["status"] = "failed"
            else:
                op["status"] = "succeeded"
                op["result"] = {"content_type": "video/mp4"}
            self.state.save()
        return {k: v for k, v in op.items() if k != "request"}

    def download(self, operation_id, destination=None):
        self.state.bump("download")
        op = self.state.doc["source_ops"].get(operation_id)
        if op is None or op["status"] != "succeeded":
            raise ProviderError("not_downloadable", http_status=409)
        post = self.state.doc["posts"][op["request"]["post_id"]]
        if post["downloads_interrupted"] < post["interrupt_downloads"]:
            post["downloads_interrupted"] += 1
            self.state.save()
            raise ProviderError("transfer_interrupted", transient=True)
        data = self._media_bytes(post)
        if destination:
            Path(destination).write_bytes(data)
        return {"sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "path": destination}

    def _media_bytes(self, post):
        if post["media"] == "image":
            return _TINY_PNG
        if post["media"].startswith("file:") and self.media_dir:
            return (self.media_dir / post["media"][5:]).read_bytes()
        raise ProviderError("media_unavailable", http_status=404)

    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id:
            op = self.state.doc["source_ops"].get(operation_id)
            return dict(op) if op else None
        return None

    def cancel(self, operation_id):
        op = self.state.doc["source_ops"].get(operation_id)
        if op:
            op["status"] = "cancelled"
            self.state.save()

    def refresh_url(self, post_id):
        """Approved refresh path: returns a fresh signed media URL."""
        post = self.state.doc["posts"][post_id]
        post["url_state"] = "fresh"
        self.state.doc["refreshes"] += 1
        n = self.state.doc["refreshes"]
        post["media_url"] = (f"https://cdn.fake/{post_id}/media"
                             f"?sig=refreshed{n}")
        self.state.save()
        return post["media_url"]

    def _next_seq(self):
        self.state.doc["seq"] += 1
        return self.state.doc["seq"]

    def counters(self):
        return {"submit": self.state.doc["counters"]["submit"],
                "download": self.state.doc["counters"]["download"],
                "refreshes": self.state.doc["refreshes"]}


class FakeDiscovery:
    """Paid research search fake (F10): paginated results, a persistent
    credit balance, one credit charged per search call — restarts see
    the same balance (no automatic top-up)."""

    def __init__(self, name, state_dir, ids, clock, credits=0):
        self.name = name
        self.ids = ids
        self.clock = clock
        self.state = FakeProviderState(Path(state_dir) / f"{name}.json")
        self.state.doc.setdefault("credits", credits)
        self.state.doc.setdefault("result_sets", {})   # "q|p" -> [posts]
        self.state.doc.setdefault("search_ops", {})
        self.state.save()

    def set_credits(self, n):
        self.state.doc["credits"] = n
        self.state.save()

    def set_results(self, query, page, posts):
        self.state.doc["result_sets"][f"{query}|{page}"] = posts
        self.state.save()

    def credits(self):
        return self.state.doc["credits"]

    # -- provider protocol -------------------------------------------------
    def submit(self, request):
        if self.state.doc["credits"] <= 0:
            raise ProviderError("insufficient_credits", http_status=402)
        self.state.doc["credits"] -= 1
        self.state.doc["charges"].append(
            {"kind": "search", "credits": 1, "at": self.clock.iso(),
             "query": request.get("query"), "page": request.get("page")})
        self.state.bump("submit")
        posts = self.state.doc["result_sets"].get(
            f"{request.get('query')}|{request.get('page')}", [])
        op_id = f"{self.name}-search:{self._next_seq()}"
        op = {"operation_id": op_id, "status": "succeeded",
              "result": {"posts": posts}, "request": request}
        self.state.doc["search_ops"][op_id] = op
        self.state.save()
        return {k: v for k, v in op.items() if k != "request"}

    def poll(self, operation_id):
        op = self.state.doc["search_ops"].get(operation_id)
        if op is None:
            raise ProviderError("unknown_operation", http_status=404)
        return {k: v for k, v in op.items() if k != "request"}

    def download(self, operation_id, destination=None):
        raise ProviderError("not_downloadable", http_status=409)

    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id:
            op = self.state.doc["search_ops"].get(operation_id)
            return dict(op) if op else None
        return None

    def cancel(self, operation_id):
        pass

    def _next_seq(self):
        self.state.doc["seq"] += 1
        return self.state.doc["seq"]

    def counters(self):
        return {"submit": self.state.doc["counters"]["submit"],
                "charges": len(self.state.doc["charges"]),
                "credits": self.state.doc["credits"]}
