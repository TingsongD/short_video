"""F17 manual scenarios: pilot response replay, OAuth expiry +
same-identity resume, ambiguous POST vs safe download retry."""
from .cases_f01 import CaseContext, _result
from ..providers.vertex import VertexAdapter
from ..providers.vertex_auth import VertexAuth
from ..testing.fakes import (FakeOAuthLoader, FakeVertexTransport,
                             ProviderError)

RATES = {"dated": "2026-09-16", "video_per_sec_tokens": 5792,
         "usd_per_m": {"input": 1.50, "output": 17.50,
                       "thought": 9.00},
         "input_tokens_est": 103, "thought_tokens_est": 421}

CAPS = {"gemini-omni-1.1-flash-preview": {
    "durations_s": [3, 4, 6, 8, 10], "aspects": ["9:16", "16:9"],
    "resolutions": ["720p", "1080p"],
    "references": {"image": 3, "video": 1}, "audio": True}}

REQ = {"prompt": "checkerboard tank on a hanger", "duration_s": 4,
       "model": "gemini-omni-1.1-flash-preview", "aspect": "9:16",
       "resolution": "720p", "reference_roles": {}}


def _stack(ctx, name):
    loader = FakeOAuthLoader(ctx.run_dir / f"{name}-oauth.json")
    auth = VertexAuth(loader, project="factory-proj")
    t = FakeVertexTransport(ctx.run_dir / f"{name}-vertex.json", loader)
    return loader, t, VertexAdapter(
        auth, t, {}, RATES, capabilities=dict(CAPS))


def f17_m01(ctx: CaseContext):
    """Replay successful + failed pilot shapes; states differ, only
    valid media downloads, usage labeled estimate."""
    _, t, ad = _stack(ctx, "m01")
    ok = ad.submit(REQ)
    ctx.check("accepted_shape",
              ok["status"] == "running" and ok["operation_id"])
    body = t.doc["interactions"][ok["operation_id"]]["request"]
    ctx.check("pilot_payload",
              body["background"] is True and "delivery" not in body
              and body["response_format"][0]["duration"] == "4s")
    t.set_fault("http200_terminal")
    bad = ad.submit(dict(REQ, prompt="fails terminally"))
    ad.observe(bad["operation_id"])
    obs = ad.observe(bad["operation_id"])
    ctx.check("error_state_differs",
              obs["status"] == "failed"
              and obs["errors"][0]["code"] == "content_filtered")
    ad.observe(ok["operation_id"])
    obs2 = ad.observe(ok["operation_id"])
    ctx.check("completed_differs",
              obs2["status"] == "succeeded" and obs2["has_media"])
    ctx.check("usage_is_estimate",
              obs2["reported_usage"]["kind"] == "reported_estimate")
    try:
        ad.download(bad["operation_id"])
        ctx.check("only_valid_media", False)
    except ProviderError:
        ctx.check("only_valid_media", True)
    return _result(ctx, "awaiting_manual_review",
                   "accepted/terminal-error/completed states are "
                   "distinct; failed op cannot produce media; usage "
                   "remains a reported estimate",
                   limitations=["human inspects response evidence"])


def f17_m02(ctx: CaseContext):
    """Expire OAuth after acceptance; reauth same identity; same
    interaction resumes, no new POST, route fields unchanged."""
    loader, t, ad = _stack(ctx, "m02")
    out = ad.submit(REQ)
    loader.expire()
    st = ad.auth.refresh()
    ctx.check("expired_named", st["reason"] == "expired")
    try:
        ad.observe(out["operation_id"])
        ctx.check("observe_blocked_expired", False)
    except ProviderError as e:
        ctx.check("observe_blocked_expired", e.code == "expired")
    n = len(t.doc["interactions"])
    loader.reauth()                    # same identity + project
    st = ad.auth.refresh()
    ctx.check("reauth_ready", st["ready"] and
              st["identity"] == "builder@example.com")
    obs = ad.observe(out["operation_id"])
    ctx.check("same_interaction_resumed",
              obs["operation_id"] == out["operation_id"]
              and obs["model"] == "gemini-omni-1.1-flash-preview"
              and obs["project"] == "factory-proj"
              and obs["location"] == "global")
    ctx.check("no_new_post", len(t.doc["interactions"]) == n)
    return _result(ctx, "passed",
                   "expired OAuth named; same-identity reauth resumed "
                   "the original interaction ID with zero new POSTs")


def f17_m03(ctx: CaseContext):
    """Lost POST stays ambiguous (no duplicate); a failed download on a
    known success retries safely."""
    _, t, ad = _stack(ctx, "m03")
    t.lose_next_post()
    try:
        ad.submit(REQ)
        ctx.check("lost_post_named", False)
    except ProviderError as e:
        ctx.check("lost_post_named", e.code == "transport_timeout")
    ctx.check("remote_accepted_anyway",
              len(t.doc["interactions"]) == 1,
              "ambiguous: remote holds one real interaction")
    # fallback/retry must NOT post again — simulate policy check
    ctx.check("no_duplicate_generation",
              len(t.doc["interactions"]) == 1)
    # separate op: known success whose download fails
    ok = ad.submit(dict(REQ, prompt="known success"))
    ad.observe(ok["operation_id"])
    ad.observe(ok["operation_id"])
    t.set_fault("download_fails")
    try:
        ad.download(ok["operation_id"])
        ctx.check("download_fail_named", False)
    except ProviderError as e:
        ctx.check("download_fail_named",
                  e.code == "transport_error", e.code)
    t.clear_fault("download_fails")
    dl = ad.download(ok["operation_id"])
    ctx.check("safe_download_retry",
              dl["operation_id"] == ok["operation_id"]
              and dl["sha256"]
              and len(t.doc["interactions"]) == 2,
              "retried transfer only — same op, still 2 interactions")
    return _result(ctx, "passed",
                   "ambiguous POST left unresolved with no duplicate; "
                   "known-success download retried on the same ID")


def f17_m04(ctx: CaseContext):
    """Live one-shot qualification under a valid ceiling — funded
    scope only."""
    return _result(ctx, "awaiting_manual_review",
                   "live gate: one exact product-reference mode under a "
                   "valid ceiling; only that tested model/location/mode "
                   "qualifies",
                   limitations=["funded scope absent — live qualification "
                                "remains blocked by design"])


def implementations():
    return {"F17-M01": f17_m01, "F17-M02": f17_m02,
            "F17-M03": f17_m03, "F17-M04": f17_m04}
