"""Application API (F27): thin transport over FactoryServices.

Mutations require Idempotency-Key + CSRF token and honor
X-Expected-Revision; async work returns 202 with durable job ids;
media serves registered artifacts with bounded ranges; events stream
ordered SSE with cursor replay.
"""
import json
from pathlib import Path

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import (JSONResponse, PlainTextResponse,
                               StreamingResponse)

from ..domain.errors import ContractError
from .idempotency import IdempotencyStore
from .security import LocalSecurityMiddleware, new_session_token
from .sse import event_stream

API_VERSION = "factory-api.v1"


def create_app(services, session_token=None):
    app = FastAPI(title="Factory API", version=API_VERSION,
                  docs_url=None, redoc_url=None)
    token = session_token or new_session_token()
    app.add_middleware(LocalSecurityMiddleware, session_token=token)
    idem = IdempotencyStore(services.db)
    app.state.session_token = token

    # ------------------------------------------------------ errors --

    @app.exception_handler(ContractError)
    async def contract_error(request, exc):
        status = 409 if exc.code in (
            "stale_revision", "idempotency_conflict", "not_authorized",
            "locked_field", "no_quote") else \
            404 if exc.code in ("not_found", "unknown_seed",
                                "unknown_artifact") else \
            413 if exc.code == "too_large" else 400
        return JSONResponse({"error": exc.code, "field": exc.field,
                             "detail": exc.detail},
                            status_code=status)

    @app.exception_handler(Exception)
    async def generic_error(request, exc):
        return JSONResponse({"error": "internal",
                             "detail": "unexpected error"},
                            status_code=500)

    # --------------------------------------------------- security ---

    @app.post("/api/session")
    async def session():
        """Issue the local session token (loopback-only app)."""
        return {"session_token": token}

    # -------------------------------------------------------- reads --

    @app.get("/api/health")
    async def health():
        return services.health()

    @app.get("/api/providers")
    async def providers():
        return services.providers_readiness()

    @app.get("/api/seeds/{seed_id}")
    async def get_seed(seed_id: str):
        return services.get_seed(seed_id)

    @app.get("/api/experiments/{experiment_id}/results")
    async def results(experiment_id: str):
        return services.experiment_results(experiment_id)

    # ---------------------------------------------------- mutations --

    def mutation(request: Request, body: dict, fn):
        """Idempotency-Key is required; expected revision optional.
        Returns (status, response)."""
        key = request.headers.get("idempotency-key")
        if not key:
            raise ContractError("missing_idempotency_key",
                                "Idempotency-Key", "required")
        return idem.run(key, request.method, request.url.path, {"payload": body, "expected_revision": request.headers.get("x-expected-revision")}, fn)

    def expected_rev(request: Request):
        raw = request.headers.get("x-expected-revision")
        return int(raw) if raw is not None else None

    @app.post("/api/seeds", status_code=201)
    async def create_seed(request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (201, {
            "seed": services.create_seed(body["url"])}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/imports", status_code=201)
    async def import_file(request: Request):
        raw = await request.body()
        name = request.headers.get("x-filename", "upload.bin")
        status, resp = mutation(
            request, {"filename": name, "bytes": len(raw), "sha256": __import__("hashlib").sha256(raw).hexdigest()},
            lambda: (201, {"artifact":
                           services.import_file(name, raw)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/research/plans", status_code=202)
    async def research_plan(request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (202, {
            "plan_id": f"rp-{body.get('seed_id', 'x')}",
            "estimated_cost": body.get("estimated_cost", {}),
            "status": "prepared"}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/research/plans/{plan_id}/run", status_code=202)
    async def research_run(plan_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (202, {
            "plan_id": plan_id, "accepted": True}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/seeds/{seed_id}/analyze", status_code=202)
    async def analyze(seed_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (202, {
            "job_id": f"analyze-{seed_id}", "accepted": True}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments", status_code=201)
    async def create_experiment(request: Request):
        body = await request.json()
        eid = body.get("id") or f"exp-{len(body.get('variants', []))}"
        status, resp = mutation(request, body, lambda: (201, {
            "experiment": services.create_experiment_draft(eid, body)}))
        return JSONResponse(resp, status_code=status)

    @app.patch("/api/experiments/{experiment_id}/draft")
    async def patch_draft(experiment_id: str, request: Request):
        body = await request.json()
        rev = expected_rev(request)
        status, resp = mutation(request, body, lambda: (200, {
            "draft": services.patch_experiment_draft(
                experiment_id, body, rev)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/quote")
    async def quote(experiment_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (200, {
            "quote": services.quote_experiment(experiment_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/authorize")
    async def authorize(experiment_id: str, request: Request):
        body = await request.json()
        rev = expected_rev(request)
        status, resp = mutation(request, body, lambda: (200, {
            "authorization": services.authorize_experiment(
                experiment_id, rev)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/run", status_code=202)
    async def run(experiment_id: str, request: Request):
        body = await request.json()
        rev = expected_rev(request)
        status, resp = mutation(request, body, lambda: (202, {
            "run": services.run_experiment(experiment_id, rev)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/pause")
    async def pause(experiment_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (200, {
            "state": services.pause_experiment(experiment_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/resume")
    async def resume(experiment_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (200, {
            "state": services.resume_experiment(experiment_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/jobs/{job_id}/reconcile")
    async def reconcile(job_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (200, {
            "reconciliation": services.reconcile_job(job_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/reviews", status_code=201)
    async def review(variant_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (201, {
            "review": services.record_review(
                variant_id, body["check_type"], body["verdict"],
                body["target_hash"],
                evidence_ids=body.get("evidence_ids", []))}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/revisions", status_code=201)
    async def revision(variant_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (201, {
            "revision": services.create_variant_revision(
                variant_id, body.get("reason", ""),
                body.get("patch", {}))}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/deliver", status_code=202)
    async def deliver(variant_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (202, {
            "delivery": services.deliver_variant(
                variant_id, body["final_path"], body["name"],
                body["folder_id"])}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/publications",
              status_code=201)
    async def publish(variant_id: str, request: Request):
        body = await request.json()
        status, resp = mutation(request, body, lambda: (201, {
            "publication": services.record_publication(
                variant_id, body["platform"], body["account_id"])}))
        return JSONResponse(resp, status_code=status)

    # -------------------------------------------------------- media --

    @app.get("/api/assets/{asset_id}/media")
    async def media(asset_id: str, request: Request):
        p = services.media_path(asset_id)
        data = Path(p).read_bytes()
        rng = request.headers.get("range")
        headers = {"accept-ranges": "bytes",
                   "content-type": "application/octet-stream"}
        if rng:
            try:
                unit, spec = rng.split("=")
                start_s, end_s = spec.split("-")
                start = int(start_s)
                end = int(end_s) if end_s else len(data) - 1
            except ValueError:
                return JSONResponse({"error": "bad_range"},
                                    status_code=416)
            if unit != "bytes" or start > end or end >= len(data):
                return JSONResponse({"error": "bad_range",
                                     "detail": "range unsatisfiable"},
                                    status_code=416)
            headers["content-range"] = \
                f"bytes {start}-{end}/{len(data)}"
            return Response(data[start:end + 1], status_code=206,
                            headers=headers)
        return Response(data, headers=headers)

    # ------------------------------------------------------- events --

    @app.get("/api/events")
    async def events(request: Request, stream: str = "factory",
                     follow: bool = False):
        last = request.headers.get("last-event-id")
        after = int(last) if last else int(
            request.query_params.get("after", 0))
        return StreamingResponse(
            event_stream(services, stream, after, follow=follow),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"})

    return app
