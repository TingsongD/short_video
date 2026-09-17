"""Generated references (F18 checklist 2): authorized Canvas image
generation riding F05 reservations + F07 intents. Manual import and
reuse remain the default path; no Vertex image generation is implied.
"""
import hashlib
import json

from ..domain.errors import ContractError


class ReferenceGeneration:
    """Submits image-reference generation through the shared executor
    so an interrupted request reconciles by identity — never a blind
    resubmission."""

    def __init__(self, db, packs, artifacts, adapter, executor, budget):
        self.db = db
        self.packs = packs
        self.artifacts = artifacts
        self.adapter = adapter          # CanvasAdapter (image kind)
        self.executor = executor        # F07 Executor (provider=adapter)
        self.budget = budget            # F05 BudgetService

    def request(self, pack_id, ref_id, job_id, prompt, lines,
                model="", attempt_seq=1, authorization_id=None, attempt_id=None):
        """lines: [(budget_id, int credits)] — sized by the caller from
        the adapter's price table. Returns {attempt_id, reservation_id,
        operation} or {attempt_id, error}."""
        self.packs._require_pack(pack_id)
        req = {"kind": "image", "prompt": prompt,
               "model": model or (self.adapter.models[0]
                                  if self.adapter.models else ""),
               "duration_s": 1}
        wire = json.dumps(req, sort_keys=True, default=str)
        rh = hashlib.sha256(wire.encode()).hexdigest()
        prepared = self.executor.require_request(attempt_id, req)
        if prepared["job_id"] != job_id:
            raise ContractError("operation_identity_conflict", "job_id", job_id)
        res = prepared["reservation_id"]
        op = self.executor.submit(
            attempt_id, lambda: self.adapter.submit(req))
        return {"attempt_id": attempt_id, "reservation_id": res,
                "request_hash": rh, "operation": op}

    def collect(self, pack_id, ref_id, role, operation_id,
                attempt_id="", variant_id="", now=""):
        """Observe → download → intake → pending reference. A download
        failure retries the transfer only."""
        obs = self.adapter.observe(operation_id)
        if obs["status"] != "succeeded":
            return {"status": obs["status"]}
        dl = self.adapter.download(operation_id)
        payload = dl["bytes"]
        if isinstance(payload, str):
            payload = payload.encode()
        art = self.artifacts.intake_bytes(
            payload, provenance="jimeng_canvas",
            source_key=f"canvas:{operation_id}",
            source_detail="generated reference",
            requested_kind="image")
        ref = self.packs.add_reference(
            pack_id, ref_id, role, art.id, origin="generated",
            variant_id=variant_id, generation_attempt_id=attempt_id,
            now=now)
        return {"status": "collected", "reference": ref.to_dict(),
                "artifact_id": art.id}

    def recover(self, pack_id, ref_id, role, attempt_id, request_hash,
                variant_id="", now=""):
        """After restart: reconcile the original attempt by request
        hash; only a terminal absence permits a new attempt."""
        rec = self.adapter.reconcile(request_hash=request_hash)
        if rec is None:
            return {"status": "no_remote_trace",
                    "action": "reconcile_or_review_evidence"}
        if rec.get("operation_id"):
            return self.collect(pack_id, ref_id, role,
                                rec["operation_id"], attempt_id,
                                variant_id, now)
        return {"status": rec.get("status", "unknown")}
