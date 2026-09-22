"""Application API (F27): thin transport over FactoryServices.

Mutations require Idempotency-Key + CSRF token and honor
X-Expected-Revision; async work returns 202 with durable job ids;
media serves registered artifacts with bounded ranges; events stream
ordered SSE with cursor replay.
"""
import json
import hashlib
import tempfile
import mimetypes
from ..events.redact import redact
from ..diagnostics import event
from pathlib import Path

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import (JSONResponse, PlainTextResponse,
                               StreamingResponse)

from ..domain.errors import ContractError
from .idempotency import IdempotencyStore
from .security import LocalSecurityMiddleware, new_session_token
from .sse import event_stream
from .inputs import json_command
from starlette.concurrency import run_in_threadpool

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
        event("request_blocked", code=exc.code,
              route=getattr(request.scope.get('route'), 'path', 'unmatched'))
        status = 409 if exc.code in (
            "stale_revision", "idempotency_conflict", "not_authorized",
            "locked_field", "no_quote", "idempotency_unresolved") else \
            404 if exc.code in ("not_found", "unknown_seed",
                                "unknown_artifact", "unknown_experiment", "unknown_variant") else \
            413 if exc.code == "too_large" else 400
        return JSONResponse(redact({"error": exc.code, "field": exc.field,
                             "detail": exc.detail}),
                            status_code=status)

    @app.exception_handler(Exception)
    async def generic_error(request, exc):
        event("request_failed", error_type=type(exc).__name__,
              route=getattr(request.scope.get('route'), 'path', 'unmatched'))
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
    async def providers(request: Request):
        # Readiness can spawn subprocesses — never on the event loop.
        force = request.query_params.get('refresh') == '1'
        return await run_in_threadpool(services.providers_readiness, force)

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
        def guarded():
            from ..budget.service import BudgetService
            for field in ('budget_ids', 'add_budget_ids'):
                if field in body:
                    BudgetService(services.db).require_selection(body[field])
            return fn()
        return idem.run_local(key, request.method, request.url.path, {"payload": body, "expected_revision": request.headers.get("x-expected-revision")}, guarded)

    def expected_rev(request: Request):
        raw = request.headers.get("x-expected-revision")
        try:
            return int(raw) if raw is not None else None
        except ValueError:
            raise ContractError("invalid_revision", "X-Expected-Revision")

    @app.post("/api/seeds", status_code=201)
    async def create_seed(request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (201, {
            "seed": services.create_seed(body["url"])}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/imports", status_code=201)
    async def import_file(request: Request):
        from ..services.app import MAX_UPLOAD_BYTES
        name = request.headers.get("x-filename", "upload.bin")
        size = 0; digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(suffix=".part") as temp:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ContractError("too_large", "size")
                digest.update(chunk); temp.write(chunk)
            temp.flush()
            status, resp = await run_in_threadpool(mutation, request, {"filename":name,"bytes":size,"sha256":digest.hexdigest()},
                lambda:(201,{"artifact":services.import_file(name,path=temp.name)}))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/seeds/{seed_id}/analysis/prepare')
    async def analysis_prepare(seed_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(201,{'plan':services.require('analysis_work').prepare(seed_id,body)}))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/seeds/{seed_id}/analysis/collect')
    async def analysis_collect(seed_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.require('analysis_work').queue_collect(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/products/import-plan')
    async def product_import_plan(request:Request):
        body=await json_command(request)
        if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
        status,resp=mutation(request,body,lambda:(201,{'plan':services.effect_work.prepare('research','shopify','admin-2026-04',[{'shop':body.get('shop',''),'selection':body.get('selection')}])}))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/analytics/reporting/prepare')
    async def reporting_prepare(request:Request):
        body=await json_command(request)
        if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
        status,resp=mutation(request,body,lambda:(201,{'plan':services.require('effect_work').prepare('research','youtube_reporting','channel_reach_basic_a1',[{'name':body.get('name','Factory thumbnail reach'),'report_type':'channel_reach_basic_a1'}])}))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/effects/plans')
    async def effect_plan(request:Request):
        body=await json_command(request)
        kind=body.get('kind');eid=body.get('experiment_id','')
        if kind not in ('tts','music','analysis') or not eid:raise ContractError('invalid_effect_plan','kind/experiment_id')
        revision=expected_rev(request);services._current(eid,revision,True)
        status,resp=mutation(request,body,lambda:(201,{'plan':services.require('effect_work').prepare(kind,body.get('provider',''),body.get('model',''),body.get('requests'),eid,revision)}))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/effects/plans/{plan_id}/authorize')
    async def effect_authorize(plan_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('effect_work').authorize(plan_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/effects/plans/{plan_id}/run')
    async def effect_run(plan_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.require('effect_work').queue(plan_id,body.get('authorization_id',''))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{eid}/speech/fit')
    async def speech_fit(eid:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.require('audio_work').queue_fit(eid,expected_rev(request),body)))
        return JSONResponse(resp,status_code=status)

    @app.get('/api/speech/{sid}')
    async def speech_detail(sid:str):return services.detail('speechsegment',sid)

    @app.post('/api/speech/{sid}/approve')
    async def speech_approve(sid:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('audio_work').approve(sid,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{eid}/speech/attach')
    async def speech_attach(eid:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('audio_work').attach(eid,expected_rev(request),body.get('speech_ids'))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/attempts/{attempt_id}/reconcile-invalid-analysis')
    async def reconcile_invalid_analysis(attempt_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (200,
            services.reconcile_invalid_analysis(attempt_id, body)))
        return JSONResponse(resp, status_code=status)

    @app.post('/api/jobs/{job_id}/retry-local')
    async def retry_local_job(job_id:str,request:Request):
        from ..services.recovery import retry_local
        body=await json_command(request)
        if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
        services.commands.get(job_id)
        status,resp=mutation(request,body,lambda:(202,services.commands.enqueue('retry_local',{'job_id':job_id,'reviewer':body['reviewer']},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/jobs/{job_id}/release-local')
    async def release_local_job(job_id:str,request:Request):
        body=await json_command(request)
        if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
        services.commands.get(job_id)
        status,resp=mutation(request,body,lambda:(202,services.commands.enqueue('release_local',{'job_id':job_id,'reviewer':body['reviewer']},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{eid}/assets/replace')
    async def replace_picture(eid:str,request:Request):
        from ..services.recovery import manual_replace
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,manual_replace(services,eid,expected_rev(request),body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/research/plans")
    async def research_plan(request: Request):
        body=await json_command(request)
        def prepare():
            requests=body.get('requests') or []
            for item in requests:
                if not isinstance(item,dict) or item.get('kind') not in ('search','creator_history') or type(item.get('page')) is not int or not 1<=item['page']<=10 or type(item.get('page_size')) is not int or not 1<=item['page_size']<=100:
                    raise ContractError('invalid_research_request','requests')
            return 201,{'plan':services.require('effect_work').prepare('research','viral_outliers','search',requests)}
        status,resp=mutation(request,body,prepare)
        return JSONResponse(resp,status_code=status)

    @app.get('/api/research/plans/{plan_id}')
    async def research_detail(plan_id:str):return services.require('effect_work').get(plan_id)

    @app.post('/api/research/plans/{plan_id}/authorize')
    async def research_authorize(plan_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('effect_work').authorize(plan_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/research/plans/{plan_id}/run")
    async def research_run(plan_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.require('effect_work').queue(plan_id,body.get('authorization_id',''))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/research/evaluate',status_code=202)
    async def research_evaluate(request:Request):
        body=await json_command(request)
        if not isinstance(body.get('plan_ids'),list) or not body['plan_ids']:raise ContractError('research_plans_required','plan_ids')
        from ..domain.records import content_hash
        inputs={**body,'run_id':'research-'+content_hash(body)[:24]}
        status,resp=mutation(request,body,lambda:(202,services.require('commands').enqueue('research_evaluate',inputs,identity=inputs['run_id'])))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/budgets',status_code=201)
    async def budget(request:Request):
        body=await json_command(request)
        def create():
            from ..budget import BudgetService
            if not body.get('reviewer') or not body.get('evidence') or not {'id','unit','scope','scope_key','ceiling'}<=body.keys():raise ContractError('budget_scope_required','reviewer/evidence/budget')
            if str(body['id']).startswith('authority:'):
                raise ContractError('budget_not_selectable','id','Internal authorization ceilings are managed by the effect ledger.')
            result=BudgetService(services.db).create_budget(body['id'],body['unit'],body['scope'],body['scope_key'],body['ceiling'])
            with services.db.uow() as u:u.events.append('factory','budget_scope_recorded',body)
            return 201,{'budget_id':body['id']}
        status,resp=mutation(request,body,create)
        return JSONResponse(resp,status_code=status)

    @app.post('/api/budgets/{budget_id}/tighten')
    async def tighten_budget(budget_id:str,request:Request):
        body=await json_command(request)
        from ..budget import BudgetService
        status,resp=mutation(request,body,lambda:(200,BudgetService(services.db).tighten_budget(
            budget_id,body.get('ceiling'),body.get('expected_ceiling'),body.get('reviewer'),body.get('evidence'))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/reservations/{reservation_id}/settle')
    async def settle_reservation(reservation_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.settle_reservation(reservation_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/reservations/{reservation_id}/release')
    async def release_reservation(reservation_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.release_reservation(reservation_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/reservations/{reservation_id}/adjust')
    async def adjust_reservation(reservation_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.adjust_reservation(reservation_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/budgets/resolve-overrun')
    async def resolve_overrun(request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.resolve_overrun(body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/seeds/{seed_id}/analyze", status_code=202)
    async def analyze(seed_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.analyze_seed(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    # ------------------------------------ mandatory deep analysis --

    @app.post("/api/seeds/{seed_id}/analysis", status_code=202)
    async def start_analysis(seed_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.start_analysis(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.get("/api/analysis/{seed_id}")
    async def get_analysis(seed_id: str):
        return services.analysis_for(seed_id)

    @app.put("/api/analysis/{seed_id}/{section}")
    async def save_analysis_section(seed_id: str, section: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.save_analysis_section(seed_id,section,body,body.get('reviewer',''))))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/analysis/{seed_id}/transcript")
    async def import_transcript(seed_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.import_analysis_transcript(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/analysis/{seed_id}/declare")
    async def declare_analysis(seed_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.declare_analysis(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/analysis/{seed_id}/rerun", status_code=202)
    async def rerun_analysis(seed_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.rerun_analysis_stages(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/analysis/{seed_id}/review")
    async def review_analysis(seed_id: str, request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.review_analysis(seed_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/seeds/{seed_id}/media")
    async def attach(seed_id: str,request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,{"seed":services.attach_media(seed_id,body['artifact_id'],role=body.get('role','master'))}))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/autoruns", status_code=201)
    async def autorun_create(request: Request):
        body = await json_command(request)
        status,resp=mutation(request,body,lambda:(201,{"run":services.autorun.create(body)}))
        return JSONResponse(resp,status_code=status)

    @app.get("/api/autoruns/{run_id}")
    async def autorun_detail(run_id: str):
        return {"run":services.autorun.detail(run_id)}

    @app.post("/api/autoruns/{run_id}/resume")
    async def autorun_resume(run_id: str,request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,{"run":services.autorun.resume(run_id,body)}))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/autoruns/{run_id}/recover-analysis-response')
    async def autorun_recover_analysis(run_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (200,
            {'run': services.autorun.recover_analysis_response(run_id, body)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/blueprints/{blueprint_id}/review")
    async def review_blueprint(blueprint_id: str,request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,{"blueprint":services.review_blueprint(blueprint_id,body)}))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/templates",status_code=201)
    async def template(request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(201,{"template":services.author_template(body)}))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/experiments/{experiment_id}/assets/review")
    async def asset_review(experiment_id: str,request: Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.review_assets(experiment_id,body,expected_rev(request))))
        return JSONResponse(resp,status_code=status)

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str):
        return services.require('commands').get(job_id)

    @app.get("/api/collections/{name}")
    async def collection(name: str):
        return {"items":services.collection(name)}

    @app.get('/api/dashboard/history')
    async def dashboard_history():
        from ..services.history import DashboardHistory
        return DashboardHistory(services.db).snapshot()

    @app.post('/api/dashboard/history')
    async def update_dashboard_history(request: Request):
        from ..services.history import DashboardHistory
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (
            200, DashboardHistory(services.db).update(body)))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments", status_code=201)
    async def create_experiment(request: Request):
        body = await json_command(request)
        body['workflow'] = {'version': 2, 'prompt_policy': 'scene.v2',
                            'qc_policy': 'visual.v2', 'visual_qc': False}
        eid = body.get("id") or "exp-"+__import__("uuid").uuid4().hex
        status, resp = mutation(request, body, lambda: (201, {
            "experiment": services.create_experiment_draft(eid, body)}))
        return JSONResponse(resp, status_code=status)

    @app.patch("/api/experiments/{experiment_id}/draft")
    async def patch_draft(experiment_id: str, request: Request):
        body = await json_command(request)
        rev = expected_rev(request)
        status, resp = mutation(request, body, lambda: (200, {
            "draft": services.patch_experiment_draft(
                experiment_id, body, rev)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/quote")
    async def quote(experiment_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (202, {
            "quote": services.quote_experiment(experiment_id, expected_rev(request))}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/authorize")
    async def authorize(experiment_id: str, request: Request):
        body = await json_command(request)
        rev = expected_rev(request)
        status, resp = mutation(request, body, lambda: (200, {
            "authorization": services.authorize_experiment(
                experiment_id, rev, body)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/run", status_code=202)
    async def run(experiment_id: str, request: Request):
        body = await json_command(request)
        rev = expected_rev(request)
        status, resp = mutation(request, body, lambda: (202, {
            "run": services.run_experiment(experiment_id, rev)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/pause")
    async def pause(experiment_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (200, {
            "state": services.pause_experiment(experiment_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/experiments/{experiment_id}/resume")
    async def resume(experiment_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (200, {
            "state": services.resume_experiment(experiment_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/jobs/{job_id}/reconcile")
    async def reconcile(job_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (200, {
            "reconciliation": services.reconcile_job(job_id)}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/reviews", status_code=201)
    async def review(variant_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (201, {
            "review": services.record_review(
                variant_id, body["check_type"], body["verdict"],
                body["target_hash"],
                reviewer=body.get("reviewer", ""), notes=body.get("notes", ""), evidence_ids=body.get("evidence_ids", []))}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/revisions", status_code=201)
    async def revision(variant_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (201, {
            "revision": services.create_variant_revision(
                variant_id, body.get("reason", ""),
                body.get("patch", {}))}))
        return JSONResponse(resp, status_code=status)

    @app.post('/api/variants/{variant_id}/delivery/reconcile', status_code=202)
    async def reconcile_delivery(variant_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (202,
            services.reconcile_external_delivery(variant_id, body, expected_rev(request))))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/deliver", status_code=202)
    async def deliver(variant_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (202, {
            "delivery": services.deliver_variant(
                variant_id, body, expected_rev(request))}))
        return JSONResponse(resp, status_code=status)

    @app.post("/api/variants/{variant_id}/publications",
              status_code=201)
    async def publish(variant_id: str, request: Request):
        body = await json_command(request)
        status, resp = mutation(request, body, lambda: (201, {
            "publication": services.record_publication(
                variant_id, body, expected_rev(request))}))
        return JSONResponse(resp, status_code=status)

    @app.get('/api/publications/{publication_id}')
    async def publication_detail(publication_id:str):return services.detail('publication',publication_id)

    @app.post('/api/experiments/{experiment_id}/publications',status_code=201)
    async def publications_batch(experiment_id:str,request:Request):
        body=await json_command(request);revision=expected_rev(request)
        status,resp=mutation(request,body,lambda:(201,services.require('publication_work').plan_batch(experiment_id,body,revision)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/publications/{publication_id}/cancel-remote',status_code=200)
    async def publication_cancel_remote(publication_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('publishing').cancel_remote(publication_id)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/publications/{publication_id}/authorize')
    async def publication_authorize(publication_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('publication_work').authorize(publication_id,body)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/publications/{publication_id}/run',status_code=202)
    async def publication_run(publication_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.require('publication_work').queue(publication_id)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/publications/{publication_id}/observe',status_code=202)
    async def publication_observe(publication_id:str,request:Request):
        body=await json_command(request)
        services.detail('publication',publication_id)
        status,resp=mutation(request,body,lambda:(202,services.require('commands').enqueue('publication_observe',{'publication_id':publication_id},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/publications/{publication_id}/readbacks',status_code=202)
    async def readback(publication_id:str,request:Request):
        body=await json_command(request);services.require('readback');services.detail('publication',publication_id)
        from ..analytics.service import COMPLETE_DAYS,HORIZONS
        if body.get('horizon') not in HORIZONS and body.get('horizon') not in COMPLETE_DAYS:raise ContractError('unknown_horizon','horizon')
        status,resp=mutation(request,body,lambda:(202,services.commands.enqueue('readback',{'publication_id':publication_id,'horizon':body['horizon']},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/variants/{variant_id}/metadata',status_code=201)
    async def metadata_create(variant_id:str,request:Request):
        body=await json_command(request)
        def create():
            services.detail('variantplan',variant_id)
            pkg=services.require('metadata').create(
                variant_id,body.get('platform',''),
                final_sha256=body.get('final_sha256',''),
                candidates=body.get('candidates'),
                generator=body.get('generator'),
                context=body.get('context'),
                disclosures=body.get('disclosures'))
            return 201,{'metadata_package':pkg.to_dict()}
        status,resp=mutation(request,body,create)
        return JSONResponse(resp,status_code=status)

    @app.get('/api/metadata/{package_id}')
    async def metadata_detail(package_id:str):
        body=services.detail('metadatapackage',package_id)
        row=services.db.uow().records.get('metadatapackage',package_id)
        return {**body,'version':row['version'] if row else None}

    @app.put('/api/metadata/{package_id}/select')
    async def metadata_select(package_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('metadata').select(
            package_id,candidate_id=body.get('candidate_id',''),
            fields=body.get('fields'),revision=expected_rev(request),
            reviewer=body.get('reviewer',''))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/metadata/{package_id}/freeze')
    async def metadata_freeze(package_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('metadata').freeze(
            package_id,revision=expected_rev(request))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{experiment_id}/policy',status_code=201)
    async def policy(experiment_id:str,request:Request):
        body=await json_command(request);revision=expected_rev(request);services._current(experiment_id,revision,True)
        def freeze():
            if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
            fields={k:v for k,v in body.items() if k in ('policy_version','primary_metric','horizon','min_exposure','practical_lift','exposure_metric','guardrails','comparison_rule','promote_min_independent_experiments','seed_policy')}
            if not {'policy_version','primary_metric','horizon'}<=fields.keys():raise ContractError('policy_required','policy')
            return 201,{'policy':services.require('learning').freeze_policy(experiment_id,revision,**fields).to_dict()}
        status,resp=mutation(request,body,freeze)
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{experiment_id}/decisions',status_code=202)
    async def decision(experiment_id:str,request:Request):
        body=await json_command(request);revision=expected_rev(request);services._current(experiment_id,revision,True)
        status,resp=mutation(request,body,lambda:(202,services.require('commands').enqueue('decision',{'experiment_id':experiment_id,'revision':revision,'horizon':body.get('horizon',''),'platform':body.get('platform',''),'account':body.get('account','')},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{experiment_id}/selections',status_code=202)
    async def selection(experiment_id:str,request:Request):
        body=await json_command(request);revision=expected_rev(request);services._current(experiment_id,revision,True)
        status,resp=mutation(request,body,lambda:(202,services.require('commands').enqueue('select_seed',{'experiment_id':experiment_id,'revision':revision,'horizon':body.get('horizon',''),'account':body.get('account',''),'accounts':body.get('accounts')},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/experiments/{experiment_id}/rounds',status_code=201)
    async def propose_round(experiment_id:str,request:Request):
        body=await json_command(request);revision=expected_rev(request);services._current(experiment_id,revision,True)
        status,resp=mutation(request,body,lambda:(201,services.require('rounds').propose_next(
            experiment_id,revision,body.get('selection_id',''))))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/series/{series_id}/loop',status_code=201)
    async def freeze_loop(series_id:str,request:Request):
        body=await json_command(request)
        def freeze():
            if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
            fields={k:v for k,v in body.items() if k in ('mode','max_rounds','max_posts','allowed_providers','allowed_accounts','spend_caps','valid_until','stop_conditions','authorization_id')}
            return 201,{'loop':services.require('rounds').freeze_loop(series_id,**fields)}
        status,resp=mutation(request,body,freeze)
        return JSONResponse(resp,status_code=status)

    @app.get('/api/series/{series_id}')
    async def series_lineage(series_id:str):
        return services.require('rounds').lineage(series_id)

    @app.post('/api/series/{series_id}/pause')
    async def series_pause(series_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('rounds').pause_series(series_id)))
        return JSONResponse(resp,status_code=status)

    @app.post('/api/series/{series_id}/cancel')
    async def series_cancel(series_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(200,services.require('rounds').cancel_series(series_id)))
        return JSONResponse(resp,status_code=status)

    @app.post("/api/variants/{variant_id}/studio",status_code=202)
    async def studio_open(variant_id:str,request:Request):
        body=await json_command(request)
        def command():
            variant,final,path,binding=services._final(variant_id)
            services._current(variant['experiment_id'],expected_rev(request),True)
            from ..domain.records import content_hash
            return 202,services.commands.enqueue('studio_open',{'variant_id':variant_id,'binding':binding,
                'session_id':'studio-'+content_hash(binding)[:20]},experiment_id=variant['experiment_id'],revision=variant['experiment_revision'])
        status,resp=mutation(request,body,command)
        return JSONResponse(resp,status_code=status)

    @app.post("/api/studio/{session_id}/close",status_code=202)
    async def studio_close(session_id:str,request:Request):
        body=await json_command(request)
        status,resp=mutation(request,body,lambda:(202,services.commands.enqueue('studio_close',{'session_id':session_id},phase='collect')))
        return JSONResponse(resp,status_code=status)

    @app.get("/api/studio/sessions")
    async def studio_sessions():
        rows=services.db.conn.execute("SELECT body FROM records WHERE kind='studio_session'").fetchall()
        return {'items':[json.loads(r[0]) for r in rows]}

    @app.post("/api/variants/{variant_id}/comments",status_code=201)
    async def studio_comment(variant_id:str,request:Request):
        body=await json_command(request)
        def comment():
            v=services.detail('variantplan',variant_id);exp=services._current(v['experiment_id'],expected_rev(request),True)
            at=body.get('at_s');fps=exp.output_clock['num']/exp.output_clock['den']
            if type(at) not in (int,float) or not 0<=at<v['target_frames']/fps or not body.get('text','').strip():
                raise ContractError('invalid_comment','at_s/text')
            import uuid
            return 201,services.studio.import_comment(uuid.uuid4().hex,variant_id,at,body['text'],exp.revision)
        status,resp=mutation(request,body,comment)
        return JSONResponse(resp,status_code=status)

    # -------------------------------------------------------- media --

    @app.get("/api/assets/{asset_id}/media")
    async def media(asset_id: str, request: Request):
        p, row = await run_in_threadpool(services.media_info, asset_id)
        size=row['byte_count']; start,end=0,size-1; status=200
        headers={"accept-ranges":"bytes","content-type":"application/octet-stream"}
        probe=json.loads(row['probe'] or '{}'); fmt=probe.get('format_name','')
        codec=next((x.get('codec_name','') for x in probe.get('streams',[]) if x.get('codec_type')=='video'),'')
        if row['kind']=='video': headers['content-type']='video/webm' if 'webm' in fmt else 'video/mp4' if 'mp4' in fmt else 'video/quicktime'
        elif row['kind']=='audio': headers['content-type']='audio/wav' if 'wav' in fmt else 'audio/mpeg' if 'mp3' in fmt else 'audio/mp4'
        elif row['kind']=='image': headers['content-type']='image/'+{'mjpeg':'jpeg'}.get(codec,codec or 'png')
        rng=request.headers.get('range')
        if rng:
            try:
                unit,spec=rng.split('='); first,last=spec.split('-')
                if unit!='bytes' or ',' in spec: raise ValueError()
                if first:
                    start=int(first); end=min(int(last),size-1) if last else size-1
                else:
                    count=int(last)
                    if count<=0: raise ValueError()
                    start=max(0,size-count)
                if start<0 or start>=size or end<start: raise ValueError()
            except ValueError:
                return JSONResponse({'error':'bad_range'},status_code=416,headers={'content-range':f'bytes */{size}'})
            status=206; headers['content-range']=f'bytes {start}-{end}/{size}'
        headers['content-length']=str(end-start+1)
        def chunks():
            with Path(p).open('rb') as stream:
                stream.seek(start); remaining=end-start+1
                while remaining>0:
                    chunk=stream.read(min(65536,remaining))
                    if not chunk: break
                    remaining-=len(chunk); yield chunk
        return StreamingResponse(chunks(),status_code=status,headers=headers)

    # ------------------------------------------------------- events --

    @app.get("/api/events")
    async def events(request: Request, stream: str = "factory",
                     follow: bool = False):
        last = request.headers.get("last-event-id")
        try:
            after = int(last) if last else int(request.query_params.get("after", 0))
            if after<0:raise ValueError()
        except ValueError:
            raise ContractError("invalid_cursor","after")
        return StreamingResponse(
            event_stream(services, stream, after, follow=follow),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"})

    # API and production frontend use a single loopback origin.
    dashboard = Path(__file__).resolve().parents[3] / 'apps/factory-dashboard/dist'
    if dashboard.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount('/',StaticFiles(directory=dashboard,html=True),name='dashboard')
    return app
