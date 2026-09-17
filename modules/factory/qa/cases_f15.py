from modules.factory.testing.authority import approve_operation
"""F15 manual scenarios: explicit routing both ways, ineligible
combinations, scoped authorization, fallback suppression."""
from .cases_f01 import CaseContext, _result
from ..domain.errors import ContractError
from ..domain.records import (Authorization, GenerationRequest,
                              ProviderPolicy)
from ..execution import Executor
from ..providers import (CapabilityCatalog, CapabilitySnapshot,
                         ProviderRouter)
from ..providers.catalog import snapshot_id
from ..store import Database
from ..testing.fakes import (FakeGenerationAdapter, FakeProvider,
                             JIMENG_MODELS, VERTEX_MODELS)

NOW = "2026-09-16T12:00:00Z"


def _stack(ctx, name, jimeng_support="qualified",
           vertex_support="observed"):
    db = Database(ctx.run_dir / f"{name}.db")
    jp = FakeProvider(f"{name}-j", ctx.workspace.dir("fake_remote"),
                      ctx.workspace.ids, ctx.clock, unit="jimeng_credits")
    vp = FakeProvider(f"{name}-v", ctx.workspace.dir("fake_remote"),
                      ctx.workspace.ids, ctx.clock, unit="usd_micros")
    adapters = {
        "jimeng_canvas": FakeGenerationAdapter(
            "jimeng_canvas", jp, JIMENG_MODELS, "jimeng_credits",
            "native_quote",
            {"seedance_2.0_fast_vip": {"*": 54, 4: 30, 8: 54}}),
        "google_vertex": FakeGenerationAdapter(
            "google_vertex", vp, VERTEX_MODELS, "usd_micros",
            "usage_estimate",
            {"omni-1": {"*": 100_000, 4: 60_000, 8: 120_000}})}
    catalog = CapabilityCatalog(db)
    for provider, models, support in (
            ("jimeng_canvas", JIMENG_MODELS, jimeng_support),
            ("google_vertex", VERTEX_MODELS, vertex_support)):
        for model, caps in models.items():
            for mode in ("text", "image_ref", "video_ref"):
                catalog.put(CapabilitySnapshot(
                    schema_version="capability.v1",
                    id=snapshot_id(provider, model, "", mode),
                    created_at=NOW, provider=provider, model=model,
                    input_mode=mode, support=support, capabilities=caps,
                    observed_at=NOW, valid_until="2026-10-01T00:00:00Z"))
    return db, jp, vp, adapters, catalog, ProviderRouter(
        db, adapters, catalog)


def _req(rid, roles=None, duration=4.0):
    r = GenerationRequest(
        schema_version="gen_request.v1", id=rid, created_at=NOW,
        experiment_id="exp1", experiment_revision=1, variant_key="A",
        segment_id="seg0", prompt="product shot",
        requested_duration_s=duration, required_usable_s=duration,
        reference_artifact_ids=list((roles or {}).keys()),
        reference_roles=roles or {})
    r.finalize_hash()
    return r


def f15_m01(ctx: CaseContext):
    """Route explicitly to each fake provider; inspect settings +
    identical factory contract."""
    db, jp, vp, adapters, cat, router = _stack(ctx, "m01")
    dj = router.route(_req("gr-j"), ProviderPolicy(choice="jimeng"),
                      now=NOW)
    ctx.check("jimeng_route",
              dj["provider"] == "jimeng_canvas"
              and dj["model"] == "seedance_2.0_fast_vip"
              and dj["price"].unit == "jimeng_credits")
    dv = router.route(_req("gr-v"), ProviderPolicy(choice="vertex"),
                      now=NOW)
    ctx.check("vertex_route",
              dv["provider"] == "google_vertex"
              and dv["model"] == "omni-1"
              and dv["price"].unit == "usd_micros")
    ctx.check("same_contract",
              set(dj) == set(dv), "identical decision shape")
    return _result(ctx, "awaiting_manual_review",
                   "both providers return the same decision contract; "
                   "native model + native unit preserved per route",
                   limitations=["human inspects payload summaries"])


def f15_m02(ctx: CaseContext):
    """Unsupported duration/reference and unqualified mode → zero
    submissions, explained verdicts."""
    db, jp, vp, adapters, cat, router = _stack(
        ctx, "m02", vertex_support="advertised")
    try:
        router.route(_req("gr-d", duration=9.0),
                     ProviderPolicy(choice="jimeng"), now=NOW)
        ctx.check("duration_blocked", False)
    except ContractError as e:
        ctx.check("duration_blocked",
                  "duration_uncovered" in e.detail)
    try:
        router.route(_req("gr-r", roles={"a": "video"}),
                     ProviderPolicy(choice="jimeng"), now=NOW)
        ctx.check("ref_blocked", False)
    except ContractError as e:
        ctx.check("ref_blocked",
                  "unsupported_reference_video" in e.detail)
    try:
        router.route(_req("gr-u"), ProviderPolicy(choice="vertex"),
                     now=NOW)
        ctx.check("unqualified_blocked", False)
    except ContractError as e:
        ctx.check("unqualified_blocked",
                  "unqualified_support" in e.detail)
    total = (jp.effect_counts()["submit"] +
             vp.effect_counts()["submit"])
    ctx.check("zero_submissions", total == 0, str(total))
    return _result(ctx, "passed",
                   "three ineligible routes named their reason; no "
                   "provider call was made")


def f15_m03(ctx: CaseContext):
    """Jimeng auth expired + Vertex allowed but out of scope → block;
    scoped USD authorization → vertex proceeds."""
    db, jp, vp, adapters, cat, router = _stack(ctx, "m03")
    jp.expire_auth()
    jimeng_only = Authorization(
        schema_version="authorization.v1", id="auth-j",
        created_at=NOW, scope_hash="h",
        allowed_providers=["jimeng_canvas"],
        caps={"jimeng_credits": 100}, status="authorized")
    try:
        router.route(_req("gr-a"),
                     ProviderPolicy(choice="jimeng_with_vertex_fallback"),
                     authorization=jimeng_only, now=NOW)
        ctx.check("first_blocked", False)
    except ContractError as e:
        ctx.check("first_blocked",
                  "not_in_scope" in e.detail
                  and "not_ready" in e.detail, e.detail)
    scoped = Authorization(
        schema_version="authorization.v1", id="auth-v",
        created_at=NOW, scope_hash="h",
        allowed_providers=["google_vertex"],
        caps={"usd_micros": 200_000}, status="authorized")
    d = router.route(_req("gr-b"),
                     ProviderPolicy(choice="jimeng_with_vertex_fallback"),
                     authorization=scoped, now=NOW)
    ctx.check("scoped_route", d["provider"] == "google_vertex"
              and d["price"].amount <= 200_000)
    return _result(ctx, "passed",
                   "expired jimeng + out-of-scope vertex blocked; a "
                   "scoped USD authorization routed to vertex within cap")


def f15_m04(ctx: CaseContext):
    """Original attempt unknown → an otherwise-eligible fallback stays
    suppressed; no competing paid replacement."""
    db, jp, vp, adapters, cat, _ = _stack(ctx, "m04")
    ex = Executor(db, jp, ctx.clock)
    router = ProviderRouter(db, adapters, cat, executor=ex)
    att = approve_operation(db, ex, {"prompt": "x"}, "job:g1", kind="generation", provider="jimeng_canvas", model="fast", unit="jimeng_credits")
    def lost():
        return adapters["jimeng_canvas"].provider.submit(
            {"prompt": "x"}, faults=("accept-then-timeout",))
    try:
        ex.submit(att, call=lost)
        ctx.check("ack_lost", False)
    except Exception:
        ctx.check("ack_lost", True)
    ctx.check("attempt_unknown",
              db.conn.execute("SELECT status FROM attempts WHERE id=?",
                              (att,)).fetchone()["status"] == "unknown")
    ctx.check("fallback_suppressed",
              router.fallback_blocked_reason(att)
              == "original_unresolved")
    return _result(ctx, "passed",
                   "ambiguous dispatch → attempt 'unknown'; fallback "
                   "eligibility reports original_unresolved — no "
                   "competing paid generation")


def implementations():
    return {"F15-M01": f15_m01, "F15-M02": f15_m02,
            "F15-M03": f15_m03, "F15-M04": f15_m04}
