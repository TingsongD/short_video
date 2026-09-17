"""Jimeng Canvas adapter (F16): wraps the official dreamina-canvas CLI
(`modules.assets.canvas_cli.CanvasCLI`) behind the F15 contract.

- The CLI boundary already guarantees: injectable runner, bounded
  timeouts, structured JSON only, no argv/stdout/stderr in errors, and
  credit-confirmation tokens that never leave the call frame.
- Preparation (canvas + node creation) is recoverable and idempotent
  by request_hash — a restart reuses the same IDs instead of creating
  duplicate paid nodes.
- The adapter records its own prep/operation map in `state` (a
  dict-like store); the caller's Executor records intents/attempts.
"""
import hashlib
import json

from ...assets.canvas_cli import CanvasError
from ..domain.errors import ContractError
from ..domain.money import Money
from ..testing.fakes import ProviderError
from .base import GenerationAdapter


class CanvasAdapter(GenerationAdapter):
    name = "jimeng_canvas"
    pricing_kind = "native_quote"
    unit = "jimeng_credits"

    def __init__(self, cli, state, expected_user=None,
                 price_table=None):
        """cli: CanvasCLI (runner injected). state: persistent dict-like
        for prep/op mappings. expected_user: reject a reconnection to a
        different account. price_table: {model: {duration_s: credits}}."""
        self.cli = cli
        self.state = state              # {"preps": {}, "ops": {}}
        self.state.setdefault("preps", {})
        self.state.setdefault("ops", {})
        self.expected_user = expected_user
        self.price_table = price_table or {}
        self.models = []

    # ------------------------------------------------------ readiness

    def readiness(self):
        try:
            doc = self.cli.doctor()
        except CanvasError as e:
            return {"ready": False, "reason": e.code}
        if self.expected_user and \
                doc.get("userId") != self.expected_user:
            return {"ready": False,
                    "reason": "account_mismatch"}
        return {"ready": True, "reason": "ok",
                "version": doc.get("version"),
                "region": doc.get("region"),
                "userId": doc.get("userId"),
                "isVip": doc.get("isVip")}

    def refresh_models(self):
        """Live catalog → adapter model list (F16 checklist 2)."""
        try:
            items = self.cli.catalog("video")
        except CanvasError as e:
            raise ProviderError(f"catalog_failed:{e.code}")
        self.models = [i["model"] for i in items]
        return items

    def capabilities(self, model):
        if model not in self.models:
            raise ProviderError("unknown_model")
        return self._caps[model]

    def set_capabilities(self, caps):
        self._caps = caps
        self.models = list(caps)

    # -------------------------------------------------------- pricing

    def price(self, request, duration_s, model=None):
        """Table estimate for routing; the authoritative number is the
        native node quote obtained in prepare_quote."""
        m = model or getattr(request, "model", "")
        table = self.price_table.get(m, {})
        return Money(self.unit, table.get(duration_s, table.get("*", 1)))

    # ------------------------------------------------------ lifecycle

    def _req_hash(self, request):
        wire = json.dumps(request if isinstance(request, dict)
                          else request.to_dict(), sort_keys=True,
                          default=str)
        return hashlib.sha256(wire.encode()).hexdigest()

    def prepare(self, request, title="factory-run"):
        """Idempotent canvas+node creation keyed by request hash."""
        rh = self._req_hash(request)
        prep = self.state["preps"].get(rh)
        if prep:
            return prep
        prompt = request.get("prompt") if isinstance(request, dict) \
            else request.prompt
        duration = (request.get("duration_s") if isinstance(
            request, dict) else request.requested_duration_s)
        model = (request.get("model") if isinstance(request, dict)
                 else request.model)
        canvas = self.cli.call("canvas", "create", "--title", title)
        project_id = canvas["projectId"]
        node = self.cli.call(
            "node", "create", "video", "--project-id", project_id,
            "--model", model, "--mode", "t2v",
            "--duration", duration, "--prompt", prompt)
        prep = {"project_id": project_id,
                "node_id": node["nodeId"],
                "update_id": node.get("updateId"),
                "request_hash": rh}
        self.state["preps"][rh] = prep
        return prep

    def prepare_quote(self, request):
        """Native quote through the CLI — ceiling for authorization."""
        prep = self.prepare(request)
        q = self.cli.quote(prep["project_id"], [prep["node_id"]])
        return {"prep": prep, "max_credits": q["totalMaxCredits"],
                "items": q["items"], "draft_version": q["draftVersion"]}

    def submit(self, request, price=None):
        """confirm → token → run; the token never leaves the CLI call."""
        quote = self.prepare_quote(request)
        submit_id = f"sub-{self._req_hash(request)[:12]}"
        ceiling = quote["max_credits"]
        try:
            out = self.cli.submit(quote["prep"]["project_id"],
                                  quote["prep"]["node_id"],
                                  submit_id, ceiling)
        except CanvasError as e:
            raise ProviderError(e.code, http_status=None)
        op_id = out.get("operationId") or out.get("submitId") or submit_id
        self.state["ops"][op_id] = {
            "operation_id": op_id, "submit_id": submit_id,
            "project_id": quote["prep"]["project_id"],
            "node_id": quote["prep"]["node_id"],
            "request_hash": self._req_hash(request),
            "status": "accepted", "ceiling": ceiling}
        return dict(self.state["ops"][op_id])

    def observe(self, operation_id):
        op = self.state["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        node = self.cli.node(op["project_id"], op["node_id"])
        status = {"QUEUED": "accepted", "RUNNING": "running",
                  "SUCCEEDED": "succeeded", "FAILED": "failed"}.get(
                      node.get("status"), "running")
        op["status"] = status
        out = dict(op)
        out["result"] = node.get("result") if status == "succeeded" \
            else node.get("error")
        return out

    def download(self, operation_id, destination=None):
        op = self.state["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        if op["status"] != "succeeded":
            raise ProviderError("output_not_available")
        args = ["resource", "download", "--project-id",
                op["project_id"], "--node-id", op["node_id"]]
        if destination:
            args += ["--output", str(destination)]
        try:
            data = self.cli.call(*args)
        except CanvasError as e:
            raise ProviderError(e.code, transient=True)
        return {"operation_id": operation_id,
                "bytes": data.get("bytes", b""),
                "sha256": data.get("sha256", "")}

    def _remote_op(self, operation_id=None, submit_id=None):
        """Ask the provider for an op the local map has lost — the
        reconcile path after a restart must find remote work by
        identity, not by local memory."""
        try:
            data = self.cli.call("operation", "status")
        except CanvasError as e:
            raise ProviderError(e.code)
        for item in data.get("items", []):
            if (operation_id and item.get("operationId") == operation_id) \
                    or (submit_id and item.get("submitId") == submit_id):
                return item
        return None

    def _adopt_remote(self, item):
        op = {"operation_id": item["operationId"],
              "submit_id": item.get("submitId"),
              "project_id": item.get("projectId"),
              "node_id": item.get("nodeId"),
              "request_hash": item.get("requestHash"),
              "status": "accepted"}
        self.state["ops"][op["operation_id"]] = op
        return op

    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id and operation_id in self.state["ops"]:
            return self.observe(operation_id)
        if operation_id:
            remote = self._remote_op(operation_id=operation_id)
            if remote:
                return self.observe(
                    self._adopt_remote(remote)["operation_id"])
        if request_hash:
            for op in self.state["ops"].values():
                if op["request_hash"] == request_hash:
                    return self.observe(op["operation_id"])
            remote = self._remote_op(
                submit_id=f"sub-{request_hash[:12]}")
            if remote:
                return self.observe(
                    self._adopt_remote(remote)["operation_id"])
            prep = self.state["preps"].get(request_hash)
            if prep:
                return {"operation_id": None, "status": "prepared",
                        "prep": prep}
        return None

    def cancel(self, operation_id):
        op = self.state["ops"].get(operation_id)
        if op is None:
            raise ProviderError("operation_not_found")
        try:
            self.cli.call("node", "cancel", "--project-id",
                          op["project_id"], "--node-id", op["node_id"])
        except CanvasError as e:
            raise ProviderError(e.code)
        op["status"] = "cancel_requested"
        return {"acknowledged": True, "terminal": False}
