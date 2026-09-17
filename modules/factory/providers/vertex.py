"""Vertex Interactions video transport using the sanitized successful pilot.

Only the verified text route is selectable. Reference modes remain unavailable
until their actual input contract is qualified. Credentials exist only at I/O.
"""
import base64
import hashlib
import json
import math
from .state import DurableState
from ..execution.context import current_effect
from ..execution.policy import ExecutionPolicy

from ..domain.money import Money
from ..testing.fakes import ProviderError
from .base import GenerationAdapter
from .state import receipt_locked

MAX_INLINE_BYTES = 64 * 1024 * 1024

TASK_BY_MODE = {"text": "text_to_video",
                "image_ref": "reference_to_video",
                "video_ref": "video_to_video"}

STATUS_MAP = {"in_progress": "running", "pending": "accepted", "completed": "succeeded",
              "failed": "failed", "cancelled": "cancelled"}


class LiveVertexTransport:
    def __init__(self, policy=None):
        self.policy = policy or ExecutionPolicy()
        self.policy.require_live("google_vertex")

    def __call__(self, method, url, headers, body):
        import urllib.request
        import urllib.error
        self.policy.require_live("google_vertex")
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
            headers={**headers, "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                raw = response.read(96 * 1024 * 1024 + 1)
                if len(raw) > 96 * 1024 * 1024:
                    raise ProviderError("response_too_large")
                return response.status, json.loads(raw)
        except urllib.error.HTTPError as error:
            return error.code, {"error": {"code": error.code}}



class VertexAdapter(GenerationAdapter):
    name = "google_vertex"
    pricing_kind = "usage_estimate"
    unit = "usd_micros"

    def __init__(self, auth, transport, state, rates,
                 capabilities=None, project=None, location="global"):
        """auth: VertexAuth. transport(method, url, headers, body)
        -> (status:int, json:dict). state: persistent dict for op map.
        rates: dated pricing snapshot for estimates."""
        self.auth = auth
        self.transport = transport
        self.state = state
        self.state.setdefault("ops", {})
        self.state.setdefault("submissions", {})
        if isinstance(transport, LiveVertexTransport) and not isinstance(state, DurableState):
            raise ProviderError("durable_state_required")
        self.rates = rates
        self._caps = capabilities or {}
        self.project = project or auth.project
        self.location = location or auth.location

    def _save(self):
        if hasattr(self.state, "flush"):
            self.state.flush()

    # ------------------------------------------------------ readiness

    def readiness(self):
        return self.auth.status()

    def capabilities(self, model):
        if model not in self._caps:
            raise ProviderError("unknown_model")
        return self._caps[model]

    @property
    def models(self):
        return list(self._caps)

    def _endpoint(self, suffix=""):
        return ("https://aiplatform.googleapis.com"
                f"/v1beta1/projects/{self.project}"
                f"/locations/{self.location}/interactions{suffix}")

    # -------------------------------------------------------- pricing

    def estimate(self, request, duration_s):
        """Dated usage estimate — never represented as settled billing."""
        out_tokens = int(self.rates["video_per_sec_tokens"] * duration_s)
        in_tokens = self.rates.get("input_tokens_est", 150)
        thought = self.rates.get("thought_tokens_est", 500)
        per_m = self.rates["usd_per_m"]
        micros = math.ceil((in_tokens * per_m["input"]
                      + out_tokens * per_m["output"]
                      + thought * per_m["thought"]) * 1_000_000 / 1e6)
        return {"kind": "estimate", "rates_dated": self.rates["dated"],
                "input_tokens_est": in_tokens,
                "output_tokens_est": out_tokens,
                "thought_tokens_est": thought,
                "usd_micros_est": micros}

    def price(self, request, duration_s, model=None):
        estimate = self.estimate(request, duration_s)["usd_micros_est"]
        factor = max(1.25, float(self.rates.get("reservation_factor", 1.25)))
        return Money(self.unit, math.ceil(estimate * factor))

    # ------------------------------------------------------ lifecycle

    def _input_mode(self, request):
        roles = (getattr(request, "reference_roles", None)
                 or (request.get("reference_roles")
                     if isinstance(request, dict) else {}) or {})
        kinds = set(roles.values())
        if "video" in kinds:
            return "video_ref"
        if "image" in kinds:
            return "image_ref"
        return "text"

    def _payload(self, request, model):
        request = request if isinstance(request, dict) else request.to_dict()
        mode = self._input_mode(request)
        if model != "gemini-omni-1.1-flash-preview" or mode != "text" or request.get("reference_artifact_ids"):
            raise ProviderError("input_mode_not_qualified")
        duration = request.get("requested_duration_s") or request.get("duration_s")
        cap = self.capabilities(model)
        if isinstance(self.transport,LiveVertexTransport) and 'qualified_modes' in cap and mode not in cap['qualified_modes']:
            raise ProviderError('input_mode_not_qualified')
        if duration not in cap.get("durations_s", []):
            raise ProviderError("unsupported_duration")
        aspect, resolution = request.get("aspect") or "9:16", request.get("resolution") or "720p"
        if aspect not in cap.get("aspects", []) or resolution not in cap.get("resolutions", []):
            raise ProviderError("unsupported_settings")
        return {"model": model, "background": True, "input": [{"type": "text", "text": request["prompt"]}],
                "response_format": [{"type": "video", "aspect_ratio": aspect, "resolution": resolution,
                                     "duration": f"{duration:g}s"}],
                "generation_config": {"video_config": {"task": "text_to_video"}}}

    def _req_hash(self, request, model):
        wire = json.dumps(request if isinstance(request, dict)
                          else request.to_dict(), sort_keys=True,
                          default=str)
        return hashlib.sha256(
            f"{model}|{wire}".encode()).hexdigest()

    def _post(self, body):
        try:
            status, doc = self.transport(
                "POST", self._endpoint(),
                {"Authorization": "Bearer " + self.auth.bearer(), "x-goog-user-project": self.project}, body)
        except TimeoutError:
            raise ProviderError("transport_timeout")
        except ConnectionError:
            raise ProviderError("transport_error", transient=True)
        if status in (401, 403):
            raise ProviderError(
                {401: "expired", 403: "missing_permission"}[status])
        if status == 429:
            raise ProviderError("quota_exceeded", transient=True)
        if status != 200:
            raise ProviderError(f"http_{status}")
        return doc

    def _get(self, interaction_id):
        try:
            status, doc = self.transport(
                "GET", self._endpoint(f"/{interaction_id}"),
                {"Authorization": "Bearer " + self.auth.bearer(), "x-goog-user-project": self.project}, None)
        except (TimeoutError, ConnectionError):
            raise ProviderError("transport_error", transient=True)
        if status == 404:
            raise ProviderError("operation_not_found")
        if status in (401, 403):
            raise ProviderError(
                {401: "expired", 403: "missing_permission"}[status])
        if status != 200:
            raise ProviderError(f"http_{status}")
        return doc

    @receipt_locked
    def prepare(self, request, model=None):
        """No remote pre-step; the request hash binds later lookups."""
        m = model or (request.get("model") if isinstance(request, dict)
                      else getattr(request, "model", ""))
        return {"request_hash": self._req_hash(request, m),
                "model": m, "project": self.project,
                "location": self.location}

    @receipt_locked
    def submit(self, request, price=None, model=None):
        m = model or (request.get("model") if isinstance(request, dict) else request.model)
        body = self._payload(request, m)
        binding = current_effect.get()
        if isinstance(self.transport, LiveVertexTransport):
            if not binding or binding["provider"] != self.name or binding["account"] != self.project:
                raise ProviderError("authority_required")
            if not self.capabilities(m).get("live_qualified"):
                raise ProviderError("input_mode_not_qualified")
        rh = self._req_hash(request, m)
        key = binding["attempt_id"] if binding else rh
        prior = self.state["submissions"].get(key)
        if prior:
            if prior["request_hash"] != rh:
                raise ProviderError("request_conflict")
            if prior.get("operation_id"):
                return self.observe(prior["operation_id"])
            raise ProviderError("submission_unresolved")
        self.state["submissions"][key] = {"request_hash": rh, "status": "unknown"}
        self._save()
        doc = self._post(body)
        if not isinstance(doc, dict):
            raise ProviderError("invalid_response")
        iid = doc.get("id")
        if not isinstance(iid, str) or not iid or "/" in iid:
            raise ProviderError("invalid_response")
        op = {"operation_id": iid, "request_hash": rh, "model": m,
              "project": self.project, "location": self.location, "status": "accepted"}
        self.state["ops"][iid] = op
        self.state["submissions"][key].update(operation_id=iid, status="accepted")
        self._save()
        return self._apply(op, doc)

    @staticmethod
    def _videos(doc):
        return [c for step in doc.get("steps", []) for c in step.get("content", [])
                if isinstance(c, dict) and c.get("type") == "video"]

    def _apply(self, op, doc):
        if doc.get("id") != op["operation_id"]:
            raise ProviderError("operation_identity_mismatch")
        errors = doc.get("errors") or ([doc["error"]] if doc.get("error") else [])
        op["status"] = "failed" if errors else STATUS_MAP.get(doc.get("status"), "unknown")
        op["errors"] = [{"code": str(e.get("code", "terminal_error"))} for e in errors] or None
        usage = doc.get("usage")
        op["reported_usage"] = {"input_tokens": usage.get("total_input_tokens"),
            "output_tokens": usage.get("total_output_tokens"), "thought_tokens": usage.get("total_thought_tokens"),
            "kind": "reported_estimate"} if usage else None
        op["has_media"] = len(self._videos(doc)) == 1
        if op["status"] == "succeeded" and not op["has_media"]:
            op["status"] = "failed"
            op["errors"] = [{"code": "missing_output"}]
        self.state["ops"][op["operation_id"]] = op
        self._save()
        return dict(op)

    @receipt_locked
    def observe(self, operation_id):
        op = self.state["ops"].get(operation_id)
        if not op or op["project"] != self.project or op["location"] != self.location:
            raise ProviderError("operation_scope_mismatch")
        return self._apply(op, self._get(operation_id))

    @receipt_locked
    def download(self, operation_id, destination=None):
        if operation_id not in self.state["ops"]:
            raise ProviderError("operation_not_found")
        doc = self._get(operation_id)
        op = self._apply(self.state["ops"][operation_id], doc)
        if op["status"] != "succeeded":
            raise ProviderError("output_not_available")
        video = self._videos(doc)[0]
        if video.get("mime_type") != "video/mp4":
            raise ProviderError("unexpected_media_type")
        raw = video.get("data")
        if not isinstance(raw, str) or len(raw) > MAX_INLINE_BYTES * 4 // 3 + 4:
            raise ProviderError("media_size_out_of_bounds")
        try:
            payload = base64.b64decode(raw, validate=True)
        except Exception:
            raise ProviderError("malformed_media") from None
        if not payload or len(payload) > MAX_INLINE_BYTES:
            raise ProviderError("media_size_out_of_bounds")
        out = {"operation_id": operation_id, "bytes": payload, "sha256": hashlib.sha256(payload).hexdigest()}
        if destination:
            from pathlib import Path
            Path(destination).write_bytes(payload)
            out["path"] = str(destination)
        return out

    @receipt_locked
    def reconcile(self, operation_id=None, request_hash=None):
        if operation_id:
            try:
                return self.observe(operation_id)
            except ProviderError as e:
                if e.code == "operation_not_found":
                    return None
                raise
        if request_hash:
            for op in self.state["ops"].values():
                if op["request_hash"] == request_hash:
                    return self.observe(op["operation_id"])
        return None

    def cancel(self, operation_id):
        raise ProviderError("cancel_not_qualified")
