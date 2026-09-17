"""Google Vertex video adapter (F17): asynchronous Interactions API
behind the F15 contract, matching the recorded pilot route.

Pilot-verified request shape (docs/vertex-video-test.md):
  POST .../projects/{project}/locations/{location}/interactions
  {"model": "gemini-omni-1.1-flash-preview", "background": true,
   "input": [{"text": ...}], "response": {"format": "video",
   "aspect_ratio": "9:16", "resolution": "720p", "duration": "4s"},
   "generation_config": {"video_config": {"task": "text_to_video"}}}

Lessons encoded:
- HTTP 200 + interaction ID is acceptance, not success — terminal
  errors arrive in `status`/`errors` on later GETs (or on the POST
  response itself).
- `delivery: "uri"` without `gcs_uri` is a confirmed terminal
  `invalid_request`; never emit `delivery` unless a bucket is
  explicitly configured.
- Usage tokens are an estimate against a dated rate snapshot —
  reported usage ≠ settled Cloud billing.
- No assumed idempotency: a lost POST response is ambiguous and must
  not be blindly resubmitted (F07 owns that decision).
"""
import base64
import hashlib
import json

from ..domain.money import Money
from ..testing.fakes import ProviderError
from .base import GenerationAdapter

MAX_INLINE_BYTES = 64 * 1024 * 1024

TASK_BY_MODE = {"text": "text_to_video",
                "image_ref": "reference_to_video",
                "video_ref": "video_to_video"}

STATUS_MAP = {"PENDING": "accepted", "RUNNING": "running",
              "SUCCEEDED": "succeeded", "FAILED": "failed",
              "CANCELLED": "cancelled"}


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
        self.rates = rates
        self._caps = capabilities or {}
        self.project = project or auth.project
        self.location = location or auth.location

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
        micros = int((in_tokens * per_m["input"]
                      + out_tokens * per_m["output"]
                      + thought * per_m["thought"]) * 1_000_000 / 1e6)
        return {"kind": "estimate", "rates_dated": self.rates["dated"],
                "input_tokens_est": in_tokens,
                "output_tokens_est": out_tokens,
                "thought_tokens_est": thought,
                "usd_micros_est": micros}

    def price(self, request, duration_s, model=None):
        return Money(self.unit,
                     self.estimate(request, duration_s)["usd_micros_est"])

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
        get = (lambda k: request.get(k) if isinstance(request, dict)
               else getattr(request, k))
        mode = self._input_mode(request)
        inputs = [{"text": get("prompt")}]
        inputs += [{"media": {"ref": rid, "role": role}}
                   for rid, role in
                   (get("reference_roles") or {}).items()]
        duration = int(round(get("requested_duration_s")
                             or get("duration_s")))
        return {"model": model, "background": True, "input": inputs,
                "response": {"format": "video",
                             "aspect_ratio": get("aspect") or "9:16",
                             "resolution": (get("resolution") or "720p"),
                             "duration": f"{duration}s"},
                "generation_config": {"video_config": {
                    "task": TASK_BY_MODE[mode],
                    "audio": bool(get("native_audio_policy") == "keep")}}}
        # `delivery`/`gcs_uri` deliberately absent unless configured.

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
                {"Authorization": "Bearer <redacted>"}, body)
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
                {"Authorization": "Bearer <redacted>"}, None)
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

    def prepare(self, request, model=None):
        """No remote pre-step; the request hash binds later lookups."""
        m = model or (request.get("model") if isinstance(request, dict)
                      else getattr(request, "model", ""))
        return {"request_hash": self._req_hash(request, m),
                "model": m, "project": self.project,
                "location": self.location}

    def submit(self, request, price=None, model=None):
        m = model or (request.get("model") if isinstance(request, dict)
                      else getattr(request, "model", ""))
        doc = self._post(self._payload(request, m))
        # HTTP 200 can still carry a terminal error or no ID at all.
        errors = doc.get("errors") or []
        if errors:
            raise ProviderError(
                errors[0].get("code", "terminal_error"))
        iid = doc.get("interactionId") or doc.get("id")
        if not iid:
            raise ProviderError("invalid_response")
        op = {"operation_id": iid,
              "request_hash": self._req_hash(request, m),
              "model": m, "project": self.project,
              "location": self.location, "status": "accepted"}
        self.state["ops"][iid] = op
        return dict(op)

    def observe(self, operation_id):
        op = self.state["ops"].get(operation_id) or \
            {"operation_id": operation_id}
        doc = self._get(operation_id)
        errors = doc.get("errors") or []
        status = STATUS_MAP.get(doc.get("status"), "running")
        if errors and status not in ("failed", "cancelled"):
            status = "failed"
        op["status"] = status
        op["errors"] = errors or None
        # usage absent → null, never zero
        usage = doc.get("usage")
        op["reported_usage"] = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "thought_tokens": usage.get("thought_tokens"),
            "kind": "reported_estimate"} if usage else None
        op["has_media"] = bool(doc.get("output", {}).get("video"))
        self.state["ops"][operation_id] = op
        return dict(op)

    def download(self, operation_id, destination=None):
        doc = self._get(operation_id)
        video = (doc.get("output") or {}).get("video")
        if not video:
            raise ProviderError("output_not_available", transient=True)
        if video.get("uri"):
            # URI delivery requires an explicitly configured bucket —
            # the pilot's `delivery: uri` without one failed terminally.
            raise ProviderError("delivery_requires_gcs")
        raw = video.get("base64")
        try:
            payload = base64.b64decode(raw, validate=True)
        except Exception:
            raise ProviderError("malformed_media")
        if not payload or len(payload) > MAX_INLINE_BYTES:
            raise ProviderError("media_size_out_of_bounds")
        out = {"operation_id": operation_id, "bytes": payload,
               "sha256": hashlib.sha256(payload).hexdigest()}
        if destination:
            with open(destination, "wb") as f:
                f.write(payload)
            out["path"] = str(destination)
        return out

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
        try:
            status, doc = self.transport(
                "POST", self._endpoint(f"/{operation_id}:cancel"),
                {"Authorization": "Bearer <redacted>"}, {})
        except (TimeoutError, ConnectionError):
            raise ProviderError("transport_error", transient=True)
        if status == 404:
            raise ProviderError("operation_not_found")
        if status != 200:
            raise ProviderError("cancel_not_supported")
        if operation_id in self.state["ops"]:
            self.state["ops"][operation_id]["status"] = \
                "cancel_requested"
        return {"acknowledged": True,
                "terminal": doc.get("status") == "CANCELLED"}
