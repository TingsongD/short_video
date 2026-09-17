"""Fake remote providers with durable effects (F01).

State persists under <workspace>/fake_remote/<provider>.json — deliberately
independent of the application database — so "worker crashed after the
provider accepted" is a real condition, not a status edit.

Counters record billable submissions, polls, downloads, uploads and
publishes. Fault scripts from qa.faults modify behavior at named points;
an accepted operation retains its identity and reservation semantics.
"""
import base64
import hashlib
import json
from pathlib import Path

from ..integrations.drive import DriveAdapter


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
        payload_fn = getattr(self, "payload_fn", None)
        payload = payload_fn(operation_id) if payload_fn else \
            f"fake-media:{self.name}:{operation_id}".encode()
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


class FakeShopify:
    """Scriptable read-only Shopify adapter (F11): paginated catalog
    from the shopify-catalog fixture shape, media downloads from a local
    directory, expiring URLs, and removable read permissions."""

    def __init__(self, name, state_dir, ids, clock, catalog=None,
                 media_dir=None):
        self.name = name
        self.ids = ids
        self.clock = clock
        self.media_dir = Path(media_dir) if media_dir else None
        self.state = FakeProviderState(Path(state_dir) / f"{name}.json")
        d = self.state.doc
        d.setdefault("catalog", catalog or {"shop": "", "pages": []})
        d.setdefault("refreshed", {})      # media_id -> fresh url
        d.setdefault("denied", [])         # media ids w/o read permission
        d.setdefault("graphql_calls", 0)
        self.state.save()

    # -- adapter interface -------------------------------------------------
    def products_page(self, cursor=None, page_size=10):
        pages = self.state.doc["catalog"]["pages"]
        idx = int(cursor) if cursor else 0
        if idx >= len(pages):
            raise ProviderError("bad_cursor", http_status=400)
        page = pages[idx]
        return {"products": page["products"],
                "hasNextPage": bool(page.get("hasNextPage")),
                "endCursor": str(idx + 1)}

    def media_page(self, product_id, cursor=None, page_size=10):
        for p in self._products():
            if p["id"] == product_id:
                return {"media": p.get("media", []), "hasNextPage": False,
                        "endCursor": None}
        raise ProviderError("product_not_found", http_status=404)

    def product_by_handle(self, handle):
        for p in self._products():
            if p.get("handle") == handle:
                return p
        raise ProviderError("product_not_found", http_status=404)

    def product_by_id(self, product_id):
        for p in self._products():
            if p["id"] == product_id:
                return p
        raise ProviderError("product_not_found", http_status=404)

    def refresh_media_url(self, media_id):
        """Fresh signed URL for an expired media link."""
        url = f"https://cdn.fixture/refreshed-{media_id.rsplit('/', 1)[-1]}"
        self.state.doc["refreshed"][media_id] = url
        self.state.save()
        return url

    def media_download(self, url):
        media_id = self._media_id_for(url)
        if media_id in self.state.doc["denied"]:
            raise ProviderError("missing_scope", http_status=403)
        m = self._media_entry(media_id)
        if m and m.get("expires") and media_id not in \
                self.state.doc["refreshed"]:
            raise ProviderError("expired_source", http_status=410)
        name = url.split("?")[0].rsplit("/", 1)[-1]
        if self.media_dir:
            path = self.media_dir / name
            if path.is_file():
                return path.read_bytes(), "application/octet-stream"
        if name.startswith("refreshed-"):
            orig = self._media_entry(media_id)
            if orig:
                base = orig["url"].split("?")[0].rsplit("/", 1)[-1]
                path = self.media_dir / base if self.media_dir else None
                if path and path.is_file():
                    return path.read_bytes(), "application/octet-stream"
        raise ProviderError("media_unavailable", http_status=404)

    # -- manipulation for drills --------------------------------------------
    def remove_permission(self, media_id):
        denied = self.state.doc["denied"]
        if media_id not in denied:
            denied.append(media_id)
            self.state.save()

    def _products(self):
        return [p for page in self.state.doc["catalog"]["pages"]
                for p in page["products"]]

    def _media_id_for(self, url):
        for p in self._products():
            for m in p.get("media", []):
                if m.get("url") == url or \
                        self.state.doc["refreshed"].get(m["id"]) == url:
                    return m["id"]
        return url.rsplit("/", 1)[-1]

    def _media_entry(self, media_id):
        for p in self._products():
            for m in p.get("media", []):
                if m["id"] == media_id:
                    return m
        return None


class FakeAnalyzer(FakeProvider):
    """Scripted multimodal analyzer (F12): accepts an analysis request
    (artifact sha + probed features), succeeds on poll, and returns the
    scripted payload for that sha — or a duration-fitted default.
    Faults: 'malformed-analysis' → succeeds with an invalid payload;
    standard FakeProvider faults (accept-then-timeout etc.) all apply."""

    def __init__(self, name, state_dir, ids, clock, scripts=None):
        super().__init__(name, state_dir, ids, clock, unit="usd_micros")
        self.scripts = scripts or {}

    def poll(self, operation_id):
        op = self.state.doc["operations"].get(operation_id)
        scripted = None
        if op is not None and op.get("request"):
            sha = op["request"].get("artifact_sha256")
            scripted = self.scripts.get(sha)
        out = super().poll(operation_id)
        if out.get("status") == "succeeded" and \
                "malformed-analysis" in out.get("faults", []):
            out["result"] = {"analysis": {"beats": [{"role": "nonsense"}]}}
            op = self.state.doc["operations"][operation_id]
            op["result"] = out["result"]
            self.state.save()
        elif out.get("status") == "succeeded":
            req = self.state.doc["operations"][operation_id]["request"]
            out["result"]["analysis"] = scripted or self._default(req)
            self.state.doc["operations"][operation_id][
                "result"]["analysis"] = out["result"]["analysis"]
            self.state.save()
        return out

    def submit(self, request, faults=(), price=None):
        # keep the request body on the op so poll can script per-sha —
        # including when the ack is lost after acceptance
        try:
            op = super().submit(request, faults=faults, price=price)
        except Exception:
            for stored in self.state.doc["operations"].values():
                if stored.get("request") is None:
                    stored["request"] = request
            self.state.save()
            raise
        if isinstance(op, dict) and "operation_id" in op:
            stored = self.state.doc["operations"][op["operation_id"]]
            stored["request"] = request
            self.state.save()
        return op

    @staticmethod
    def _default(request):
        """Duration-fitted 3-beat default when no script matches."""
        dur = float(request.get("duration_s") or 10.0)
        marks = [dur * f for f in (0.15, 0.75)]
        return {
            "beats": [
                {"id": "b1", "role": "hook", "start_s": 0.0,
                 "end_s": marks[0], "visual_event": "opener",
                 "confidence": "uncertain"},
                {"id": "b2", "role": "body", "start_s": marks[0],
                 "end_s": marks[1], "visual_event": "main",
                 "confidence": "uncertain"},
                {"id": "b3", "role": "cta", "start_s": marks[1],
                 "end_s": dur, "visual_event": "closer",
                 "confidence": "uncertain"}],
            "transcript": [], "music": {"role": "unknown"},
            "uncertainty": ["default_script"]}


class FakeGenerationAdapter:
    """Scriptable generation adapter (F15): capability catalog +
    price table in front of a persistent FakeProvider."""

    def __init__(self, name, provider, models, unit, pricing_kind,
                 price_table=None):
        self.name = name
        self.provider = provider
        self.models = models           # {model: capabilities dict}
        self.unit = unit
        self.pricing_kind = pricing_kind
        # {model: {duration_s: amount}} — default flat 1 per request
        self.price_table = price_table or {}

    def readiness(self):
        ok = self.provider.state.doc.get("authenticated", True)
        return {"ready": bool(ok),
                "reason": "ok" if ok else "auth_expired"}

    def capabilities(self, model):
        if model not in self.models:
            raise ProviderError("unknown_model")
        return self.models[model]

    def validate(self, request, capabilities):
        from ..providers.base import GenerationAdapter
        return GenerationAdapter.validate(self, request, capabilities)

    def price(self, request, duration_s, model=None):
        from ..domain.money import Money
        m = model or getattr(request, "model", "") or \
            (request.get("model") if isinstance(request, dict) else "")
        table = self.price_table.get(m, {})
        amount = table.get(duration_s, table.get("*", 1))
        return Money(self.unit, amount)

    def prepare(self, request):
        return {"prepared": True, "node": f"node-{self.name}"}

    def submit(self, request, price=None):
        wire = {"prompt": request.get("prompt")
                if isinstance(request, dict) else request.prompt,
                "duration_s": (request.get("duration_s") if isinstance(
                    request, dict) else request.requested_duration_s)}
        return self.provider.submit(
            wire, price=({"unit": price.unit, "amount": price.amount}
                         if price else None))

    def observe(self, operation_id):
        return self.provider.poll(operation_id)

    def download(self, operation_id, destination=None):
        return self.provider.download(operation_id, destination)

    def reconcile(self, operation_id=None, request_hash=None):
        return self.provider.reconcile(operation_id=operation_id,
                                       request_hash=request_hash)

    def cancel(self, operation_id):
        return self.provider.cancel(operation_id)


JIMENG_MODELS = {
    "seedance_2.0_fast_vip": {
        "durations_s": [4, 8], "aspects": ["9:16"],
        "resolutions": ["720x1280", "1080x1920"],
        "references": {"image": 3, "video": 0}, "audio": False}}
VERTEX_MODELS = {
    "omni-1": {
        "durations_s": [4, 6, 8], "aspects": ["9:16"],
        "resolutions": ["720x1280", "1080x1920"],
        "references": {"image": 2, "video": 1}, "audio": True}}


_TINY_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                 "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class _Completed:
    def __init__(self, rc, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = rc, stdout, stderr


class FakeCanvasRunner:
    """Argv-level fake of the dreamina-canvas CLI (F16): persistent
    JSON state (auth, account, credits, canvases, nodes, ops, catalog).
    Returns CompletedProcess-shaped results; faults drill specific
    failures without touching real commands."""

    def __init__(self, path, credits=1000, user_id="u-1", region="cn"):
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {
                "loggedIn": True, "region": region, "environment": "prod",
                "userId": user_id, "isVip": True, "vipLevel": 3,
                "credits": credits, "seq": 0, "canvases": {},
                "nodes": {}, "ops": {}, "poll_counts": {},
                "faults": [], "lost_runs": [],
                "models": [{
                    "model": "seedance_2.0_fast_vip",
                    "aliases": ["seedance-fast"],
                    "modes": [{"name": "t2v", "flags": [
                        {"flag": "--duration",
                         "values": ["4", "8"], "min": 1, "max": 10,
                         "step": 1},
                        {"flag": "--ratio", "values": ["9:16", "16:9"]},
                        {"flag": "--resolution",
                         "values": ["720P", "1080P"]},
                        {"flag": "--prompt", "minLength": 1,
                         "maxLength": 2000},
                        {"flag": "--count", "min": 1, "max": 1}]}]}]}
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def _next(self, prefix):
        self.doc["seq"] += 1
        return f"{prefix}-{self.doc['seq']:05d}"

    # -- drills ---------------------------------------------------------
    def expire_login(self):
        self.doc["loggedIn"] = False
        self._save()

    def reconnect(self, user_id="u-1"):
        self.doc["loggedIn"] = True
        self.doc["userId"] = user_id
        self._save()

    def set_fault(self, name):
        if name not in self.doc["faults"]:
            self.doc["faults"].append(name)
            self._save()

    def lose_next_run(self):
        """The next `node run` accepts remotely but drops the response."""
        self.doc["lost_runs"].append("pending")
        self._save()

    # -- argv entrypoint -------------------------------------------------
    def __call__(self, cmd, capture_output=True, text=True, timeout=None):
        import subprocess as _sp
        if "cli_missing" in self.doc["faults"]:
            raise FileNotFoundError(cmd[0])
        if "transport_timeout" in self.doc["faults"]:
            raise _sp.TimeoutExpired(cmd, timeout or 60)
        args = [a for a in cmd[1:]
                if not a.startswith("--format") and
                a not in ("json", "--non-interactive")]
        # strip --profile/--region pairs
        skip = {"--profile", "--region"}
        argv, i = [], 0
        while i < len(args):
            if args[i] in skip:
                i += 2
                continue
            argv.append(args[i])
            i += 1
        try:
            data = self._dispatch(argv)
            return _Completed(0, json.dumps(
                {"schemaVersion": "1", "ok": True, "data": data}))
        except _Fault as f:
            return _Completed(30, json.dumps(
                {"schemaVersion": "1", "ok": False,
                 "error": {"code": f.code,
                           "requiredAction": f.action}}))
        except _Malformed:
            return _Completed(0, "<<not-json")

    def _flag(self, argv, name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    def _dispatch(self, argv):
        if "malformed_json" in self.doc["faults"]:
            raise _Malformed()
        head = " ".join(argv[:2])
        if argv[0] == "version":
            return {"version": "1.4.2", "commit": "abc123"}
        if argv[0] == "schema":
            return self._schema()
        if head == "auth status":
            return {"loggedIn": self.doc["loggedIn"],
                    "region": self.doc["region"],
                    "environment": self.doc["environment"]}
        if head == "auth account":
            if not self.doc["loggedIn"]:
                raise _Fault("login_required", "auth login")
            return {"userId": self.doc["userId"],
                    "isVip": self.doc["isVip"],
                    "vipLevel": self.doc["vipLevel"]}
        if head == "model list":
            return {"items": self.doc["models"]}
        if head == "canvas create":
            pid = self._next("proj")
            self.doc["canvases"][pid] = {
                "projectId": pid,
                "title": self._flag(argv, "--title", "untitled")}
            self._save()
            return {"projectId": pid}
        if head == "canvas ls":
            items = list(self.doc["canvases"].values())
            return {"items": items, "hasMore": False, "nextCursor": None}
        if head == "node create":
            nid = self._next("node")
            self.doc["nodes"][nid] = {
                "nodeId": nid,
                "projectId": self._flag(argv, "--project-id"),
                "kind": argv[2], "status": "DRAFT",
                "model": self._flag(argv, "--model"),
                "duration": self._flag(argv, "--duration"),
                "prompt": self._flag(argv, "--prompt")}
            self._save()
            return {"nodeId": nid, "updateId": self._next("upd")}
        if head == "node show":
            nid = self._flag(argv, "--node-id")
            node = self.doc["nodes"].get(nid)
            if node is None:
                return {"nodes": [{"result": "NOT_FOUND"}]}
            # progress each poll: DRAFT→QUEUED→RUNNING→SUCCEEDED
            n = self.doc["poll_counts"].get(nid, 0)
            self.doc["poll_counts"][nid] = n + 1
            if node["status"] in ("QUEUED", "RUNNING") and n >= 1:
                node["status"] = "SUCCEEDED" if \
                    "node_fails" not in self.doc["faults"] else "FAILED"
                if node["status"] == "SUCCEEDED":
                    node["result"] = {"output": f"media:{nid}"}
                else:
                    node["error"] = {"code": "generation_failed"}
            self._save()
            return {"nodes": [{"result": "FOUND", "node": node}]}
        if head == "node quote":
            wanted = [a for i, a in enumerate(argv)
                      if i and argv[i - 1] == "--node-id"]
            if "partial_quote" in self.doc["faults"] and len(wanted) > 1:
                wanted = wanted[:-1]
            items = [{"nodeId": n, "maxCredits": 54} for n in wanted]
            total = sum(i["maxCredits"] for i in items)
            return {"items": items, "totalMaxCredits": total,
                    "confirmable": True, "draftVersion": "dv-1"}
        if head == "node confirm":
            ceiling = int(self._flag(argv, "--credit-ceiling", "0"))
            if ceiling <= 0:
                raise _Fault("invalid_ceiling")
            return {"creditConfirmationToken": f"tok-{self._next('tok')}",
                    "creditCeiling": ceiling}
        if head == "node run":
            nid = self._flag(argv, "--node-id")
            if "credit_reject" in self.doc["faults"]:
                raise _Fault("credits_rejected", "check balance")
            self.doc["nodes"][nid]["status"] = "QUEUED"
            op = {"operationId": self._next("op"),
                  "submitId": self._flag(argv, "--submit-id"),
                  "nodeId": nid,
                  "projectId": self.doc["nodes"][nid].get("projectId")}
            self.doc["ops"][op["operationId"]] = op
            self._save()
            if self.doc["lost_runs"]:
                self.doc["lost_runs"].pop()
                self._save()
                import subprocess as _sp
                raise _sp.TimeoutExpired("node run", 60)
            return op
        if head == "node cancel":
            nid = self._flag(argv, "--node-id")
            if nid in self.doc["nodes"]:
                self.doc["nodes"][nid]["status"] = "CANCELLED"
                self._save()
            return {"cancelled": True}
        if head == "operation status":
            return {"items": list(self.doc["ops"].values())}
        if head == "resource download":
            nid = self._flag(argv, "--node-id")
            node = self.doc["nodes"].get(nid)
            if node is None or node.get("status") != "SUCCEEDED":
                raise _Fault("output_not_available")
            if "download_fails" in self.doc["faults"]:
                raise _Fault("transport_error")
            import hashlib as _h
            if node.get("kind") == "image":
                # a real 1x1 PNG so artifact intake can probe it
                payload = base64.b64decode(_TINY_PNG_B64)
            else:
                payload = f"canvas-media:{nid}".encode()
            return {"bytes_b64": base64.b64encode(payload).decode(),
                    "sha256": _h.sha256(payload).hexdigest()}
        raise _Fault(f"unknown_command:{' '.join(argv)}")

    def _schema(self):
        def node(name, flags=(), subs=()):
            return {"name": name, "flags": [{"name": f.lstrip("-")} for f in flags],
                    "subcommands": list(subs)}
        return {"subcommands": [
            node("canvas", (), [
                node("create", ["--title", "--project-id"]),
                node("ls", ["--cursor", "--limit"])]),
            node("node", (), [
                node("create", (), [
                    node("video", ["--node-id", "--update-id",
                                   "--duration", "--model", "--mode",
                                   "--project-id", "--prompt"]),
                    node("image", ["--node-id", "--update-id",
                                   "--model", "--mode", "--project-id",
                                   "--prompt"])]),
                node("quote", ["--node-id", "--project-id"]),
                node("confirm", ["--credit-ceiling", "--project-id",
                                 "--node-id"]),
                node("run", ["--submit-id", "--credit-token",
                             "--project-id", "--node-id"]),
                node("show", ["--node-id", "--project-id"]),
                node("cancel", ["--project-id", "--node-id"])]),
            node("operation", (), [
                node("status", ["--project-id"]),
                node("wait", ["--timeout"])]),
            node("resource", (), [
                node("download", ["--output", "--project-id",
                                  "--node-id"])]),
            node("auth", (), [node("status"), node("account")]),
            node("model", (), [node("list", ["--type"])]),
            node("version"), node("schema")]}


class _Fault(Exception):
    def __init__(self, code, action=None):
        self.code, self.action = code, action


class _Malformed(Exception):
    pass


class FakeOAuthLoader:
    """Persistent OAuth credential source for VertexAuth (F17).
    Drills: expire(), reauth(), switch_project(), api_key_only(),
    revoke_scope(), set_quota(ok)."""

    def __init__(self, path, project="factory-proj",
                 identity="builder@example.com"):
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {"kind": "oauth",
                        "access_token": "ya29.fake-token",
                        "expiry": "2099-01-01T00:00:00Z",
                        "expired": False, "identity": identity,
                        "project": project,
                        "scopes": ["cloud-platform"],
                        "quota_ok": True}
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def __call__(self):
        return dict(self.doc)

    def expire(self):
        self.doc["expired"] = True
        self._save()

    def reauth(self, project=None, identity=None):
        self.doc.update({"kind": "oauth", "expired": False,
                         "project": project or self.doc["project"],
                         "identity": identity or self.doc["identity"],
                         "quota_ok": True})
        self._save()

    def api_key_only(self):
        self.doc["kind"] = "api_key"
        self._save()

    def switch_project(self, project):
        self.doc["project"] = project
        self._save()

    def revoke_scope(self):
        self.doc["scopes"] = []
        self._save()

    def set_quota(self, ok):
        self.doc["quota_ok"] = bool(ok)
        self._save()


class FakeVertexTransport:
    """Persistent Interactions-API transport (F17): enforces the pilot's
    lessons — API key → 401, expired OAuth → 401, wrong project → 404,
    `delivery: uri` without `gcs_uri` → accepted-then-terminal
    invalid_request, and a lost POST response leaves a real remote
    interaction behind."""

    KNOWN_MODELS = {"gemini-omni-1.1-flash-preview"}

    def __init__(self, path, auth_loader):
        self.path = Path(path)
        self.auth_loader = auth_loader
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {"seq": 0, "interactions": {}, "polls": {},
                        "faults": [], "lost_posts": []}
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def set_fault(self, name):
        if name not in self.doc["faults"]:
            self.doc["faults"].append(name)
            self._save()

    def clear_fault(self, name):
        if name in self.doc["faults"]:
            self.doc["faults"].remove(name)
            self._save()

    def lose_next_post(self):
        self.doc["lost_posts"].append("pending")
        self._save()

    # -------------------------------------------------- transport ----
    def __call__(self, method, url, headers, body):
        cred = self.auth_loader()
        if cred.get("kind") == "api_key" or cred.get("expired") \
                or not cred.get("access_token"):
            return 401, {"error": {"code": 401,
                                   "message": "unauthenticated"}}
        # project in URL must match the credential's project
        if f"/projects/{cred['project']}/" not in url:
            return 404, {"error": {"code": 404,
                                   "message": "project not found"}}
        if "quota_429" in self.doc["faults"]:
            return 429, {"error": {"code": 429,
                                   "message": "quota exhausted"}}
        if method == "POST" and url.endswith(":cancel"):
            return self._cancel(url.rsplit("/", 1)[1][:-7])
        if method == "POST":
            return self._post(body or {})
        return self._get(url.rsplit("/", 1)[1])

    def _post(self, body):
        iid = f"int-{self.doc['seq'] + 1:05d}"
        self.doc["seq"] += 1
        interaction = {"interactionId": iid, "request": body,
                       "status": "RUNNING", "errors": [],
                       "output": {}, "usage": None}
        # pilot failure: URI delivery without a configured bucket is
        # accepted then fails terminally on the resource itself
        if body.get("delivery") == "uri" and not body.get("gcs_uri"):
            interaction["status"] = "FAILED"
            interaction["errors"] = [
                {"code": "invalid_request",
                 "message": "URI delivery requires gcs_uri"}]
        if "http200_terminal" in self.doc["faults"]:
            interaction["status"] = "FAILED"
            interaction["errors"] = [
                {"code": "content_filtered",
                 "message": "terminal failure after acceptance"}]
        if body.get("model") not in self.KNOWN_MODELS:
            interaction["status"] = "FAILED"
            interaction["errors"] = [
                {"code": "model_not_found",
                 "message": str(body.get("model"))}]
        self.doc["interactions"][iid] = interaction
        self._save()
        if self.doc["lost_posts"]:
            self.doc["lost_posts"].pop()
            self._save()
            raise TimeoutError("response lost after acceptance")
        return 200, {"interactionId": iid, "status": "RUNNING"}

    def _get(self, iid):
        it = self.doc["interactions"].get(iid)
        if it is None:
            return 404, {"error": {"code": 404,
                                   "message": "interaction not found"}}
        if "download_fails" in self.doc["faults"] \
                and it["status"] == "SUCCEEDED":
            raise ConnectionError("media retrieval transport failure")
        n = self.doc["polls"].get(iid, 0)
        self.doc["polls"][iid] = n + 1
        if it["status"] == "RUNNING" and n >= 1:
            if "missing_output" in self.doc["faults"]:
                it["status"] = "SUCCEEDED"
            elif "malformed_b64" in self.doc["faults"]:
                it["status"] = "SUCCEEDED"
                it["output"] = {"video": {"base64": "!!!not-b64!!!"}}
            else:
                it["status"] = "SUCCEEDED"
                payload = f"vertex-media:{iid}".encode()
                it["output"] = {"video": {
                    "base64": base64.b64encode(payload).decode()}}
                it["usage"] = {"input_tokens": 103,
                               "output_tokens": 23168,
                               "thought_tokens": 421}
        self._save()
        return 200, {"interactionId": iid, "status": it["status"],
                     "errors": it["errors"], "output": it["output"],
                     "usage": it["usage"]}

    def _cancel(self, iid):
        it = self.doc["interactions"].get(iid)
        if it is None:
            return 404, {"error": {"code": 404}}
        it["status"] = "CANCELLED"
        self._save()
        return 200, {"interactionId": iid, "status": "CANCELLED"}


def _wav_bytes(duration_s, freq=220.0, rate=22050):
    """Deterministic mono PCM WAV — real probeable audio for fakes."""
    import io
    import math
    import struct
    import wave
    n = max(1, int(duration_s * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(
                2 * math.pi * freq * i / rate))) for i in range(n))
        w.writeframes(frames)
    return buf.getvalue()


class FakeTTS:
    """Persistent ElevenLabs-style synthesis (F19): submit → op;
    observe polls RUNNING→SUCCEEDED; download returns a real WAV whose
    duration derives from word count. Usage = characters, an estimate
    in elevenlabs_credits — never settled billing."""

    unit = "elevenlabs_credits"

    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {"seq": 0, "ops": {}, "polls": {}, "faults": [],
                        "lost_submits": []}
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def set_fault(self, name):
        if name not in self.doc["faults"]:
            self.doc["faults"].append(name)
            self._save()

    def clear_fault(self, name):
        if name in self.doc["faults"]:
            self.doc["faults"].remove(name)
            self._save()

    def lose_next_submit(self):
        self.doc["lost_submits"].append("pending")
        self._save()

    def price(self, text):
        return max(1, -(-len(text) // 100))      # 1 credit / 100 chars

    def submit(self, request):
        if "quota" in self.doc["faults"]:
            raise ProviderError("quota_exceeded", transient=True)
        self.doc["seq"] += 1
        oid = f"tts-{self.doc['seq']:05d}"
        words = len((request.get("text") or "").split())
        duration = 0.3 + words * 0.38           # speech + edge silence
        self.doc["ops"][oid] = {
            "operation_id": oid, "request": request,
            "request_hash": hashlib.sha256(json.dumps(
                request, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "status": "RUNNING", "duration_s": round(duration, 3)}
        self._save()
        if self.doc["lost_submits"]:
            self.doc["lost_submits"].pop()
            self._save()
            raise ProviderError("transport_timeout")
        return {"operation_id": oid, "status": "accepted"}

    def observe(self, operation_id):
        op = self.doc["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        n = self.doc["polls"].get(operation_id, 0)
        self.doc["polls"][operation_id] = n + 1
        if op["status"] == "RUNNING" and n >= 1:
            op["status"] = "FAILED" if "synth_fails" in \
                self.doc["faults"] else "SUCCEEDED"
            if op["status"] == "SUCCEEDED":
                op["usage"] = {"characters":
                               len(op["request"].get("text") or "")}
        self._save()
        out = dict(op)
        out["status"] = {"RUNNING": "running", "SUCCEEDED": "succeeded",
                         "FAILED": "failed"}[op["status"]]
        return out

    def download(self, operation_id, destination=None):
        op = self.doc["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        if op["status"] != "SUCCEEDED":
            raise ProviderError("output_not_available", transient=True)
        if "download_fails" in self.doc["faults"]:
            raise ProviderError("transport_error", transient=True)
        payload = _wav_bytes(op["duration_s"])
        return {"operation_id": operation_id, "bytes": payload,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "usage": op.get("usage")}

    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id and operation_id in self.doc["ops"]:
            return self.observe(operation_id)
        if request_hash:
            for op in self.doc["ops"].values():
                if op.get("request_hash") == request_hash:
                    return self.observe(op["operation_id"])
        return None

    def cancel(self, operation_id):
        op = self.doc["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        op["status"] = "FAILED"
        self._save()
        return {"acknowledged": True, "terminal": True}


class FakeAligner:
    """Deterministic word timing: words spaced evenly inside the
    waveform's speech region (edge silence excluded)."""

    def align(self, text, audio_sha256, duration_s):
        words = (text or "").split()
        if not words:
            return []
        edge = 0.15
        span = max(0.05, (duration_s - 2 * edge) / len(words))
        return [{"w": w, "start_s": round(edge + i * span, 3),
                 "end_s": round(edge + (i + 0.92) * span, 3),
                 "confidence": 0.95}
                for i, w in enumerate(words)]


class FakeMusicGen:
    """Persistent music-generation fake (F20): own route/auth — not
    implied by video OAuth. Returns a real WAV bed; drills mirror the
    other providers."""

    name = "fake_music"
    unit = "elevenlabs_credits"

    def __init__(self, path, authed=True):
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {"seq": 0, "ops": {}, "polls": {}, "faults": [],
                        "lost_submits": [], "authed": authed}
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def set_auth(self, ok):
        self.doc["authed"] = bool(ok)
        self._save()

    def lose_next_submit(self):
        self.doc["lost_submits"].append("pending")
        self._save()

    def submit(self, request):
        if not self.doc["authed"]:
            raise ProviderError("route_auth_required")
        self.doc["seq"] += 1
        oid = f"mus-{self.doc['seq']:05d}"
        self.doc["ops"][oid] = {"operation_id": oid,
                                "request": request,
                                "status": "RUNNING"}
        self._save()
        if self.doc["lost_submits"]:
            self.doc["lost_submits"].pop()
            self._save()
            raise ProviderError("transport_timeout")
        return {"operation_id": oid, "status": "accepted"}

    def observe(self, operation_id):
        op = self.doc["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        n = self.doc["polls"].get(operation_id, 0)
        self.doc["polls"][operation_id] = n + 1
        if op["status"] == "RUNNING" and n >= 1:
            op["status"] = "SUCCEEDED"
        self._save()
        return {"operation_id": operation_id,
                "status": {"RUNNING": "running",
                           "SUCCEEDED": "succeeded"}[op["status"]]}

    def download(self, operation_id, destination=None):
        op = self.doc["ops"].get(operation_id)
        if op is None or op["status"] != "SUCCEEDED":
            raise ProviderError("output_not_available", transient=True)
        payload = _wav_bytes(6.0, freq=110.0)
        return {"operation_id": operation_id, "bytes": payload,
                "sha256": hashlib.sha256(payload).hexdigest()}

    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id and operation_id in self.doc["ops"]:
            return self.observe(operation_id)
        return None

    def cancel(self, operation_id):
        if operation_id in self.doc["ops"]:
            self.doc["ops"][operation_id]["status"] = "FAILED"
            self._save()
        return {"acknowledged": True, "terminal": True}


class FakeAudioAnalyzer:
    """Deterministic BPM/structure probe for constructed beds."""

    def __init__(self, bpm=120, structure=None):
        self.bpm = bpm
        self.structure = structure or {"sections": [
            {"name": "bed", "start_s": 0.0}]}

    def analyze(self, artifact):
        return {"duration": (artifact.probe or {}).get("duration_s"),
                "bpm": self.bpm, "structure": self.structure}


class FakeDrive(DriveAdapter):
    """Persistent Drive fake (F25): files by id with name/parent/md5/
    size/content; drills for lost acks, auth expiry, checksum gaps."""

    def __init__(self, path, authed=True):
        self.path = Path(path)
        if self.path.exists():
            self.doc = json.loads(self.path.read_text())
        else:
            self.doc = {"seq": 0, "files": {}, "uploads": 0,
                        "lost_next": False, "authed": authed,
                        "no_md5": False}
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def _auth(self):
        if not self.doc["authed"]:
            raise ProviderError("auth_expired")

    def lose_next_upload(self):
        self.doc["lost_next"] = True
        self._save()

    def set_auth(self, ok):
        self.doc["authed"] = bool(ok)
        self._save()

    def set_no_md5(self, on=True):
        self.doc["no_md5"] = on
        self._save()

    def list_files(self, parent_id):
        self._auth()
        return [{"id": f["id"], "name": f["name"], "md5": f["md5"],
                 "size": f["size"], "parent": f["parent"]}
                for f in self.doc["files"].values()
                if f["parent"] == parent_id]

    def upload(self, parent_id, path, name):
        self._auth()
        data = Path(path).read_bytes()
        self.doc["seq"] += 1
        self.doc["uploads"] += 1
        fid = f"drv-{self.doc['seq']:05d}"
        self.doc["files"][fid] = {
            "id": fid, "name": name, "parent": parent_id,
            "size": len(data), "md5": hashlib.md5(data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}
        if self.doc["lost_next"]:
            self.doc["lost_next"] = False
            self._save()
            raise ProviderError("transport_timeout")   # ack lost; file exists
        self._save()
        return {"id": fid}

    def stat(self, file_id):
        self._auth()
        f = self.doc["files"].get(file_id)
        if f is None:
            return None
        out = dict(f)
        if self.doc["no_md5"]:
            out["md5"] = None
        return out

    def plant(self, parent_id, name, content):
        """Pre-existing remote file (conflict/reuse scenarios)."""
        self.doc["seq"] += 1
        fid = f"drv-{self.doc['seq']:05d}"
        self.doc["files"][fid] = {
            "id": fid, "name": name, "parent": parent_id,
            "size": len(content), "md5": hashlib.md5(content).hexdigest(),
            "sha256": hashlib.sha256(content).hexdigest()}
        self._save()
        return fid


class FakePublisher:
    """Persistent fake Upload Post world (F31): accounts, async
    upload jobs keyed by idempotency identity, and real post objects.

    The transport sees the actual request — file bytes, fields and
    headers — so tests assert the wire contract directly. State may be
    shared across "restarts" by passing the same `doc`.
    Faults: lost_ack, oauth_expired, lost_status.
    """

    def __init__(self, users=("acct-main",), doc=None, now_fn=None,
                 faults=None):
        self.doc = doc if doc is not None else {
            "seq": 0, "jobs": {}, "by_key": {}, "posts": {}}
        self.users = set(users)
        self.faults = set(faults or [])
        self.now_fn = now_fn or (lambda: "2026-09-17T12:00:00+00:00")
        self.sent = []
        self.default_steps = ["accepted", "processing", "public"]

    # ------------------------------------------------------- wire --

    def transport(self, req):
        self.sent.append(req)
        if "oauth_expired" in self.faults:
            from ..integrations.publisher import PublishTransportError
            raise PublishTransportError("token_expired", 401)
        path = req["path"]
        if req["method"] == "POST" and path == "/api/upload":
            return {"status": 200, "body": self._upload(req)}
        if req["method"] == "GET" and path.startswith("/api/upload/status"):
            return {"status": 200, "body": self._status(path)}
        if path.startswith("/api/posts/"):
            ref = path.rsplit("/", 1)[-1]
            if req["method"] == "GET":
                return {"status": 200, "body": self._get_post(ref)}
            if req["method"] == "PATCH":
                return {"status": 200, "body": self._patch_post(
                    ref, req["fields"])}
            if req["method"] == "DELETE":
                return {"status": 200, "body": self._delete_post(ref)}
        return {"status": 404, "body": {"error": "unknown_path"}}

    # ----------------------------------------------------- upload --

    def _upload(self, req):
        from ..integrations.publisher import PublishTransportError
        fields = req["fields"]
        for need in ("user", "platform[]"):
            if not fields.get(need):
                raise PublishTransportError(
                    f"missing required field {need}", 400)
        if fields["user"] not in self.users:
            raise PublishTransportError("unknown_user", 403)
        key = req["headers"].get("Idempotency-Key")
        if not key:
            raise PublishTransportError("missing Idempotency-Key", 400)
        import hashlib
        payload = hashlib.sha256(
            repr(sorted(fields.items())).encode()
            + (req["file"]["bytes"] if req["file"] else b"")).hexdigest()
        prior = self.doc["by_key"].get(key)
        if prior:
            job = self.doc["jobs"][prior]
            if job["payload"] != payload:
                raise PublishTransportError(
                    "idempotency_payload_mismatch", 409)
            return {"request_id": prior, "status": job["steps"]
                    [min(job["i"], len(job["steps"]) - 1)]}
        self.doc["seq"] += 1
        rid = f"req-{self.doc['seq']:04d}"
        steps = (["processing", "public"] if "sync_terminal"
                 in self.faults else list(self.default_steps))
        if fields.get("schedule_date"):
            steps = ["accepted", "scheduled"]
        elif fields.get("visibility") == "draft":
            steps = ["accepted", "draft"]
        self.doc["jobs"][rid] = {
            "request_id": rid, "key": key, "payload": payload,
            "fields": fields,
            "file_bytes": len(req["file"]["bytes"]) if req["file"] else 0,
            "video_url": fields.get("video_url", ""),
            "steps": steps, "i": 0}
        self.doc["by_key"][key] = rid
        if "lost_ack" in self.faults:
            raise PublishTransportError("lost_response")
        return {"request_id": rid, "status": steps[0]}

    def _status(self, path):
        from ..integrations.publisher import PublishTransportError
        if "lost_status" in self.faults:
            raise PublishTransportError("status_unreachable")
        query = path.split("?", 1)[-1] if "?" in path else ""
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if "idempotency_key" in params:
            rid = self.doc["by_key"].get(params["idempotency_key"])
            if rid is None:
                return {"status": "not_found"}
            return self._job_body(self.doc["jobs"][rid], advance=False)
        job = self.doc["jobs"].get(params.get("request_id", ""))
        if job is None:
            return {"status": "not_found"}
        return self._job_body(job, advance=True)

    def _job_body(self, job, advance):
        if advance and job["i"] < len(job["steps"]) - 1:
            job["i"] += 1
        status = job["steps"][job["i"]]
        body = {"request_id": job["request_id"], "status": status}
        if status == "public":
            post = self._ensure_post(job)
            body.update(post_url=post["url"],
                        remote_post_id=post["id"],
                        published_at=post["published_at"],
                        visibility=post["visibility"])
        if status == "scheduled":
            body["scheduled_at"] = job["fields"].get("schedule_date", "")
        return body

    def _ensure_post(self, job):
        for p in self.doc["posts"].values():
            if p["request_id"] == job["request_id"]:
                return p
        self.doc["seq"] += 1
        pid = f"yt-{self.doc['seq']:04d}"
        post = {"id": pid, "request_id": job["request_id"],
                "url": f"https://youtu.be/{pid}",
                "account": job["fields"]["user"],
                "platform": job["fields"]["platform[]"][0],
                "visibility": job["fields"].get("visibility", "public"),
                "status": "public",
                "published_at": self.now_fn(),
                "title": job["fields"].get("title", "")}
        self.doc["posts"][pid] = post
        return post

    # ------------------------------------------------------ posts --

    def _get_post(self, ref):
        post = self.doc["posts"].get(ref)
        if post is None:
            for p in self.doc["posts"].values():
                if p["url"].endswith(ref):
                    post = p
                    break
        if post is None:
            return {"status": "not_found"}
        return dict(post)

    def _patch_post(self, ref, fields):
        post = self.doc["posts"].get(ref)
        if post is None:
            return {"status": "not_found"}
        post.update({k: v for k, v in fields.items()
                     if k in ("title", "description", "visibility")})
        return dict(post)

    def _delete_post(self, ref):
        post = self.doc["posts"].get(ref)
        if post is None:
            return {"status": "not_found"}
        post["status"] = "deleted"
        post["visibility"] = "none"
        return {"status": "deleted"}

    # ---------------------------------------------------- helpers --

    def plant_post(self, pid, **fields):
        """Insert a pre-existing remote post (manual lane conflicts)."""
        post = {"id": pid, "request_id": "",
                "url": f"https://youtu.be/{pid}",
                "account": "acct-main", "platform": "youtube",
                "visibility": "public", "status": "public",
                "published_at": "2026-09-10T09:00:00+00:00",
                "title": "manual post"}
        post.update(fields)
        self.doc["posts"][pid] = post
        return pid

    def public_post_count(self):
        return sum(1 for p in self.doc["posts"].values()
                   if p["status"] == "public")


class FakeAnalytics:
    """Fake YouTube analytics world (F32): validates that callers only
    use supported endpoint/metric combinations — the wire contract is
    the test surface.

    `transport(request)` where request = {"url","headers"}.
    Fixtures: `stats` (data api), `analytics_rows`, `reach_rows`
    (day-dimensioned), `channel_doc` for the median route.
    Faults: oauth_expired, analytics_down, reach_down, data_down,
    delayed (empty rows until cleared).
    """

    def __init__(self, stats=None, analytics_rows=None, reach_rows=None,
                 channel_doc=None, faults=None):
        self.stats = stats or {"viewCount": "2400", "likeCount": "91",
                               "commentCount": "12"}
        # columns: day + sorted(PULL_METRICS) = day, averageViewDuration,
        # averageViewPercentage, comments, likes, subscribersGained, views
        self.analytics_rows = analytics_rows if analytics_rows is not \
            None else [["2026-09-17", 18.5, 61.0, 4, 9, 3, 1000],
                       ["2026-09-18", 17.0, 58.0, 3, 7, 2, 1400]]
        self.reach_rows = reach_rows if reach_rows is not None else [
            ["2026-09-17", 38500, 6.2], ["2026-09-18", 30000, 5.8]]
        self.channel_doc = channel_doc or {
            "uploads": "UU-x", "ids": ["a", "b", "c"],
            "views": [1000, 1500, 2000]}
        self.faults = set(faults or [])
        self.requests = []

    def transport(self, req):
        from urllib.parse import urlparse, parse_qs
        self.requests.append(req)
        url = req["url"]
        p = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(p.query).items()}
        if "oauth_expired" in self.faults and \
                ("analytics" in p.netloc or "reporting" in p.netloc):
            return {"status": 401, "body": {"error": "token_expired"}}
        if "youtubeanalytics" in p.netloc:
            if "analytics_down" in self.faults:
                return {"status": 503, "body": {"error": "down"}}
            metrics = set((q.get("metrics") or "").split(","))
            from ..analytics.client import ANALYTICS_PER_VIDEO
            bad = metrics - ANALYTICS_PER_VIDEO
            if bad:
                return {"status": 400,
                        "body": {"error":
                                 f"unsupported_metrics:{sorted(bad)}"}}
            if not req["headers"].get("Authorization"):
                return {"status": 401, "body": {"error": "no_oauth"}}
            cols = ["day"] + sorted(metrics)
            rows = ([] if "delayed" in self.faults
                    else self.analytics_rows)
            return {"status": 200,
                    "body": {"columnHeaders": [{"name": c}
                                               for c in cols],
                             "rows": rows}}
        if "youtubereporting" in p.netloc:
            if "reach_down" in self.faults:
                return {"status": 503, "body": {"error": "down"}}
            if q.get("reportType") != "channel_reach_basic_a1":
                return {"status": 400,
                        "body": {"error": "unknown_report_type"}}
            metrics = set((q.get("metrics") or "").split(","))
            from ..analytics.client import REACH_METRICS
            bad = metrics - REACH_METRICS
            if bad:
                return {"status": 400,
                        "body": {"error":
                                 f"unsupported_metrics:{sorted(bad)}"}}
            if not req["headers"].get("Authorization"):
                return {"status": 401, "body": {"error": "no_oauth"}}
            cols = ["day"] + sorted(metrics)
            rows = ([] if "delayed" in self.faults else self.reach_rows)
            return {"status": 200,
                    "body": {"columnHeaders": [{"name": c}
                                               for c in cols],
                             "rows": rows}}
        if "data_down" in self.faults:
            return {"status": 503, "body": {"error": "down"}}
        if "/channels" in p.path:
            uploads = self.channel_doc.get("uploads")
            items = ([] if not uploads else [{
                "contentDetails": {"relatedPlaylists":
                                   {"uploads": uploads}}}])
            return {"status": 200, "body": {"items": items}}
        if "/playlistItems" in p.path:
            items = [{"contentDetails": {"videoId": v}}
                     for v in self.channel_doc.get("ids", [])]
            return {"status": 200, "body": {"items": items}}
        if "/videos" in p.path:
            ids = (q.get("id") or "").split(",")
            if len(ids) > 1:                       # median listing
                views = self.channel_doc.get("views", [])
                items = [{"statistics": {"viewCount": str(v)}}
                         for v in views[:len(ids)]]
            else:
                items = [{"statistics": dict(self.stats)}]
            return {"status": 200, "body": {"items": items}}
        return {"status": 404, "body": {"error": "unknown_endpoint"}}
