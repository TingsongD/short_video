"""Official Canvas 1.0.1 protocol, shared canvases and stable public identities.

Protocol source: installed schema 83aeb67 and the verified legacy batch adapter.
Only prepare creates drafts. Observation, recovery and download never run a node.
"""
import hashlib
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from ...assets.canvas_cli import CanvasError
from ...assets.canvas import new_node_id
from ..domain.money import Money
from ..execution.context import current_effect
from ..execution.policy import ExecutionPolicy
from ..testing.fakes import ProviderError
from .base import GenerationAdapter, normalized_setting
from .state import receipt_locked


class CanvasAdapter(GenerationAdapter):
    name = "jimeng_canvas"
    pricing_kind = "native_quote"
    unit = "jimeng_credits"

    def __init__(self, cli, state, expected_user=None, price_table=None,
                 policy=None, artifacts=None):
        self.cli, self.state = cli, state
        self.policy = policy or ExecutionPolicy()
        self.live = cli.runner is subprocess.run
        if self.live:
            self.policy.require_live("jimeng_canvas")
            if not hasattr(state, "flush") or not expected_user:
                raise ProviderError("durable_account_scope_required")
        self.expected_user = expected_user
        self.price_table = price_table or {}
        self.models, self._caps = [], {}
        self.artifacts = artifacts
        for key in ("canvases", "preps", "ops", "imports"):
            state.setdefault(key, {})

    def _save(self):
        if hasattr(self.state, "flush"):
            self.state.flush()

    def _merge_save(self, mutate):
        """Reload, apply and flush under one receipt lock so a mutation
        never flushes a stale whole-document snapshot over another
        worker's accepted receipts."""
        if hasattr(self.state, "locked"):
            with self.state.locked():
                mutate()
                self._save()
        else:
            mutate()
            self._save()

    def readiness(self):
        try:
            doc = self.cli.doctor()
        except CanvasError as error:
            return {"ready": False, "reason": error.code}
        if self.expected_user and doc.get("userId") != self.expected_user:
            return {"ready": False, "reason": "account_mismatch"}
        return dict(**doc,ready=True,reason="ok",installed=True,authenticated=True,catalog_visible=bool(self._caps),contract_tested=True,live_qualified=bool(self._caps) and all(c.get("live_qualified") is True for c in self._caps.values()))

    def refresh_models(self):
        items = self.cli.catalog("video")
        self.models = [i["model"] for i in items]
        return items

    def capabilities(self, model):
        if model not in self._caps:
            raise ProviderError("unknown_model")
        return self._caps[model]

    def set_capabilities(self, caps):
        self._caps, self.models = caps, list(caps)

    def price(self, request, duration_s, model=None):
        model = model or (request.get("model") if isinstance(request, dict) else request.model)
        if self.live:
            req = request if isinstance(request, dict) else request.to_dict()
            quote = self.prepare_quote(dict(req, duration_s=duration_s, model=model))
            return Money(self.unit, quote["max_credits"])
        table = self.price_table.get(model, {})
        amount = table.get(duration_s, table.get("*"))
        if amount is None:
            raise ProviderError("price_unknown")
        return Money(self.unit, amount)

    def _req_hash(self, request):
        return hashlib.sha256(json.dumps(request if isinstance(request, dict) else request.to_dict(), sort_keys=True, default=str).encode()).hexdigest()

    def _project(self, video_id, title):
        saved = self.state["canvases"].get(video_id)
        if saved:
            if saved["stage"] == "creating":
                found = self.cli.find_canvas(saved["project_id"])
                if not found:
                    raise ProviderError("canvas_creation_unresolved")
                saved["stage"] = "created"
                self._save()
            return saved["project_id"]
        saved = {"project_id": str(uuid.uuid4()), "stage": "creating"}
        self.state["canvases"][video_id] = saved
        self._save()
        out = self.cli.call("canvas", "create", title, "--project-id", saved["project_id"])
        if out.get("project", {}).get("projectId") != saved["project_id"]:
            raise ProviderError("canvas_identity_mismatch")
        saved["stage"] = "created"
        self._save()
        return saved["project_id"]

    def _references(self, request, project_id):
        refs = request.get("reference_artifact_ids") or request.get("refs") or []
        out = []
        for ref in refs:
            # The router emits typed {"kind": ..., "artifact_id": ...}
            # references; "node:"/"resource:" ids pass straight through;
            # anything else is a contract violation, not an AttributeError.
            if isinstance(ref, dict):
                ref = ref.get("artifact_id") or ref.get("id")
            if not isinstance(ref, str):
                raise ProviderError("malformed_reference")
            if ref.startswith("node:") or ref.startswith("resource:"):
                out.append(ref)
                continue
            if self.artifacts is None:
                raise ProviderError("reference_artifact_required")
            row = self.artifacts.db.uow().artifacts.get(ref)
            if not row:
                raise ProviderError("reference_artifact_missing")
            key = project_id + ":" + row["sha256"]
            imp = self.state["imports"].get(key)
            if imp is None:
                imp = {"resource_id": str(uuid.uuid4()), "node_id": new_node_id(),
                       "update_id": str(uuid.uuid4()), "submit_id": str(uuid.uuid4()), "stage": "uploading"}
                self.state["imports"][key] = imp
                self._save()
                upload = self.cli.call("resource", "upload", "--project-id", project_id,
                    "--resource-id", imp["resource_id"], "--file", self.artifacts.path_for(ref), "--type", row["kind"], "--name", ref)
                if upload.get("resourceId") != imp["resource_id"]:
                    raise ProviderError("reference_identity_mismatch")
                imp["stage"] = "uploaded"
                self._save()
            if imp["stage"] == "uploaded":
                imp["stage"] = "importing"
                self._save()
                self.cli.call("node", "create", row["kind"], "--project-id", project_id,
                    "--node-id", imp["node_id"], "--update-id", imp["update_id"], "--submit-id", imp["submit_id"],
                    "--resource-id", imp["resource_id"], "--import-kind", "local_upload")
                imp["stage"] = "imported"
                self._save()
            if imp["stage"] == "importing":
                self.cli.node(project_id, imp["node_id"])
                imp["stage"] = "imported"
                self._save()
            if imp["stage"] != "imported":
                raise ProviderError("reference_upload_unresolved")
            out.append("node:" + imp["node_id"])
        return out

    @receipt_locked
    def prepare(self, request, title="factory-run"):
        request = request if isinstance(request, dict) else request.to_dict()
        rh = self._req_hash(request)
        existing = self.state["preps"].get(rh)
        if existing:
            if existing["stage"] == "saving":
                self.cli.node(existing["project_id"], existing["node_id"])
                existing["stage"] = "saved"
                self._save()
            return existing
        video_id = request.get("video_id") or request.get("experiment_id")
        if self.live:
            cap = self.capabilities(request["model"])
            roles=set((request.get('reference_roles') or {}).values())
            mode='video_ref' if 'video' in roles else 'image_ref' if request.get('reference_artifact_ids') else 'text'
            if not cap.get("live_qualified") or ('qualified_modes' in cap and mode not in cap['qualified_modes']):
                raise ProviderError("input_mode_not_qualified")
            if (request.get("duration_s") or request.get("requested_duration_s")) not in cap.get("durations_s", []):
                raise ProviderError("unsupported_duration")
            if normalized_setting(request, "aspect", "9:16") not in cap.get("aspects", []):
                raise ProviderError("unsupported_aspect")
            if normalized_setting(request, "resolution", "720p") not in cap.get("resolutions", []):
                raise ProviderError("unsupported_resolution")
        if self.live and not video_id:
            raise ProviderError("video_scope_required")
        project_id = self._project(video_id or title, title)
        refs = self._references(request, project_id)
        kind = request.get("kind") or "video"
        prep = {"project_id": project_id, "node_id": new_node_id(), "update_id": str(uuid.uuid4()),
                "submit_id": str(uuid.uuid4()), "request_hash": rh, "kind": kind, "stage": "saving", "refs": refs}
        self.state["preps"][rh] = prep
        self._save()
        mode = request.get("mode") or (("m2v" if refs else "t2v") if kind == "video" else ("i2i" if refs else "t2i"))
        prep["expected"] = {"model": request["model"], "mode": mode,
            "ratio": normalized_setting(request, "aspect", "9:16"),
            "resolution": normalized_setting(request, "resolution", "720p" if kind == "video" else "2K"),
            "outputCount": 1, "prompt": request["prompt"]}
        if kind == "video":
            prep["expected"]["durationSeconds"] = request.get("duration_s") or request.get("requested_duration_s")
        self._save()
        args = ["node", "create", kind, "--project-id", project_id, "--node-id", prep["node_id"],
                "--update-id", prep["update_id"], "--model", request["model"],
                "--mode", mode,
                "--prompt", request["prompt"], "--ratio", normalized_setting(request, "aspect", "9:16"),
                "--resolution", normalized_setting(request, "resolution", "720p" if kind == "video" else "2K"), "--count", "1"]
        if kind == "video":
            args += ["--duration", request.get("duration_s") or request.get("requested_duration_s")]
        for ref in refs:
            args += ["--ref", ref]
        created = self.cli.call(*args)
        if created.get("node", {}).get("nodeId") != prep["node_id"]:
            raise ProviderError("node_identity_mismatch")
        prep["stage"] = "saved"
        self._save()
        return prep

    def _check_draft(self, prep):
        node = self.cli.node(prep["project_id"], prep["node_id"])
        generation = node.get("generation", {})
        if node.get("type") != prep["kind"] or any(generation.get(k) != v for k, v in prep["expected"].items()):
            raise ProviderError("draft_changed_requires_approval")
        refs = [f"{r.get('kind')}:{r.get('id')}" for r in generation.get("references", [])]
        if refs != prep["refs"]:
            raise ProviderError("draft_references_changed")

    def prepare_quote(self, request):
        prep = self.prepare(request)
        self._check_draft(prep)
        q = self.cli.quote(prep["project_id"], [prep["node_id"]])
        def record():
            saved = self.state["preps"].get(prep["request_hash"])
            if saved is not None:
                saved["quote"] = q
        self._merge_save(record)
        prep["quote"] = q
        return {"prep": prep, "max_credits": q["totalMaxCredits"], "items": q["items"], "draft_version": q["draftVersion"]}

    @receipt_locked
    def submit(self, request, price=None):
        binding = current_effect.get()
        if self.live:
            self.policy.require_live("jimeng_canvas")
            if not binding or binding["provider"] != self.name or binding["account"] != self.expected_user:
                raise ProviderError("authority_required")
            if not self.readiness()["ready"]:
                raise ProviderError("account_not_ready")
        if binding:
            approved = binding.get("approved_price")
            if approved:
                bound = Money(**approved)
                if price and price != bound:
                    raise ProviderError("price_scope_mismatch")
                price = bound
        if not isinstance(price, Money) or price.unit != self.unit:
            raise ProviderError("approved_price_required")
        prep = self.prepare(request)
        # Allocation identity: the same attempt reconciles to the same
        # operation, while a separately approved take — even an identical
        # request — gets a distinct operation and idempotency token.
        key = binding["attempt_id"] if binding and binding.get("attempt_id") else prep["submit_id"]
        previous = self.state["ops"].get(key)
        if previous:
            return self.observe(key)
        quote = self.prepare_quote(request)
        if quote["max_credits"] > price.amount:
            raise ProviderError("quote_exceeds_approval")
        op = {"operation_id": key, "submit_id": str(uuid.uuid4()), "project_id": prep["project_id"],
              "node_id": prep["node_id"], "request_hash": prep["request_hash"], "kind": prep["kind"], "status": "unknown", "ceiling": price.amount}
        self.state["ops"][op["operation_id"]] = op
        self._save()
        try:
            response = self.cli.submit(op["project_id"], op["node_id"], op["submit_id"], price.amount)
        except CanvasError as error:
            raise ProviderError(error.code) from None
        items = response.get("items", [])
        if len(items) != 1 or items[0].get("nodeId") != op["node_id"] or items[0].get("submitId") != op["submit_id"]:
            raise ProviderError("malformed_ack")
        state = str(items[0].get("state", "unknown")).lower()
        if state == "rejected":
            op["status"] = "failed"
            self._save()
            raise ProviderError("rejected_before_accept")
        if state not in {"accepted", "pending", "running", "succeeded"}:
            raise ProviderError("malformed_ack")
        op["status"] = "accepted"
        self._save()
        return dict(op)

    @receipt_locked
    def observe(self, operation_id):
        op = self.state["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        try:
            data = self.cli.call("operation", "status", op["submit_id"], "--project-id", op["project_id"], incomplete=True)
        except CanvasError as error:
            raise ProviderError(error.code) from None
        if data.get("operationRef") != op["submit_id"]:
            raise ProviderError("operation_identity_mismatch")
        state = data.get("state")
        op["status"] = {"pending": "accepted", "submitted": "accepted", "rejected": "failed"}.get(state, state if state in {"accepted", "running", "succeeded", "failed", "cancelled"} else "unknown")
        if op["status"] == "succeeded":
            resources = [r["resourceId"] for r in data.get("resources", []) if r.get("state") == "succeeded"]
            node = self.cli.node(op["project_id"], op["node_id"])
            if len(resources) != 1 or not any(r.get("resourceId") == resources[0] and r.get("submitId") == op["submit_id"] and r.get("type") == op["kind"] for r in node.get("resources", [])):
                op["status"] = "unknown"
                self._save()
                raise ProviderError("output_identity_mismatch")
            op["resource_id"] = resources[0]
        self._save()
        return dict(op)

    @receipt_locked
    def download(self, operation_id, destination=None):
        op = self.state["ops"].get(operation_id)
        if not op or op["status"] != "succeeded" or not op.get("resource_id"):
            raise ProviderError("output_not_available")
        with tempfile.TemporaryDirectory(prefix="factory-canvas-") as temporary:
            path = Path(destination) if destination else Path(temporary) / ("output.png" if op["kind"] == "image" else "output.mp4")
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = self.cli.call("resource", "download", op["resource_id"], "--project-id", op["project_id"], "--output", path, timeout=180)
            except CanvasError as error:
                raise ProviderError(error.code, transient=True) from None
            if data.get("resourceId") != op["resource_id"] or not path.is_file():
                raise ProviderError("download_identity_mismatch")
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if data.get("sha256") != digest or data.get("size") != len(payload):
                raise ProviderError("download_integrity_mismatch")
            return {"operation_id": operation_id, "bytes": payload, "sha256": digest}

    @receipt_locked
    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id:
            return self.observe(operation_id)
        matches = [o for o in self.state["ops"].values() if o["request_hash"] == request_hash]
        if len(matches) != 1:
            return None
        return self.observe(matches[0]["operation_id"])

    def cancel(self, operation_id):
        # The installed public schema exposes no cancellation command.
        raise ProviderError("cancellation_not_supported")
