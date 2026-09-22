"""Durable receipts for synchronous external effects, without invented remote jobs.

An interrupted call with no persisted response is ambiguous. Observation reads
its existing receipt; it never repeats a billable call.
"""
import fcntl
import hashlib
import json
from pathlib import Path

from .state import DurableState
from .preflight import RequestNotSent
from ..execution.context import current_effect
from ..events.redact import redact
from ..testing.fakes import ProviderError


class SynchronousAdapter:
    def __init__(self, state_dir):
        self.root = Path(state_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def submit(self, request):
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
        binding = current_effect.get()
        identity = binding["attempt_id"] if binding else digest
        operation = "sync-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        folder = self.root / operation
        folder.mkdir(exist_ok=True)
        with (folder / "lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProviderError("operation_busy") from None
            state = DurableState(folder / "receipt.json")
            if state:
                if state["request_hash"] != digest:
                    raise ProviderError("request_conflict")
                return self.poll(operation)
            state.update(operation_id=operation, request_hash=digest, request=redact(request), status="unknown")
            state.flush()
            try:
                result, payload, extra = self.execute(request)
            except RequestNotSent as error:
                state.update(status="failed", not_sent={
                    "phase": "credential_preflight", "reason": error.code,
                    "attempt_id": binding.get("attempt_id") if binding else None,
                    "request_hash": digest})
                state.flush()  # Recovery must see proof before releasing a hold.
                error.receipt = dict(state)
                raise
            except ProviderError as error:
                # Only the explicit analysis throttle response is repeatable.
                # Timeouts, 5xx and malformed success payloads stay unknown.
                if error.code == 'analysis_http_error' and error.http_status == 429:
                    state.update(status='failed', rejected={
                        'cause': error.code, 'class': 'pre_acceptance', 'http_status': 429,
                        'attempt_id': binding.get('attempt_id') if binding else None,
                        'request_hash': digest})
                    state.flush()
                    error.receipt = dict(state)
                raise
            if payload is not None:
                temporary = folder / "payload.tmp"
                temporary.write_bytes(payload)
                temporary.replace(folder / "payload")
                state.update(sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
            state.update(status="succeeded", result=redact(result), **redact(extra or {}))
            receipt = DurableState(folder / "response.json")
            receipt.update(state)
            receipt.flush()
            state.flush()
            return dict(state)

    def execute(self, request):
        raise NotImplementedError

    def readiness(self):
        return {'installed':True,'authenticated':False,
                'catalog_visible':bool(getattr(self,'model',None) or getattr(self,'pricing',None)),
                'contract_tested':bool(getattr(self,'contract_evidence',None)),
                'live_qualified':bool(getattr(self,'qualified',False)),
                'reason':'Credentials are verified at the transport boundary; no credential probe was performed'}

    def poll(self, operation_id):
        if not operation_id.startswith("sync-") or not operation_id[5:].isalnum():
            raise ProviderError("invalid_operation")
        state = DurableState(self.root / operation_id / "receipt.json")
        if not state:
            raise ProviderError("operation_not_found")
        response = self.root / operation_id / "response.json"
        if state["status"] == "unknown" and response.is_file():
            saved = json.loads(response.read_text())
            if saved.get("operation_id") == operation_id and saved.get("request_hash") == state["request_hash"]:
                state.update(saved)
                state.flush()
        return dict(state)

    observe = poll

    def download(self, operation_id, destination=None):
        state = self.poll(operation_id)
        if state["status"] != "succeeded" or not state.get("sha256"):
            raise ProviderError("output_not_available")
        payload = (self.root / operation_id / "payload").read_bytes()
        if hashlib.sha256(payload).hexdigest() != state["sha256"]:
            raise ProviderError("payload_changed")
        if destination:
            Path(destination).write_bytes(payload)
        return {"operation_id": operation_id, "bytes": payload, "sha256": state["sha256"],
                "content_type": state.get("content_type"), "path": str(destination) if destination else None,
                "alignment": state.get("alignment")}

    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id:
            return self.poll(operation_id)
        binding = current_effect.get()
        if binding and binding.get('attempt_id'):
            identity = 'sync-' + hashlib.sha256(binding['attempt_id'].encode()).hexdigest()[:32]
            if (self.root / identity / 'receipt.json').is_file():
                return self.poll(identity)
            return None
        matches = [json.loads(p.read_text()) for p in self.root.glob("sync-*/receipt.json")]
        matches = [s for s in matches if s["request_hash"] == request_hash]
        return matches[0] if len(matches) == 1 else None
