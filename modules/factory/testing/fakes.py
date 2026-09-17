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
