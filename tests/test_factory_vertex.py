"""F17: Vertex adapter — OAuth boundary, pilot payload shape,
HTTP-200 terminal errors, inline decode, estimate pricing, recovery."""
import base64

import pytest

from modules.factory.providers.vertex import VertexAdapter
from modules.factory.providers.vertex_auth import VertexAuth
from modules.factory.testing.fakes import (
    FakeOAuthLoader, FakeVertexTransport, ProviderError)

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


def make(tmp_path, project="factory-proj", state=None):
    loader = FakeOAuthLoader(tmp_path / "oauth.json", project=project)
    auth = VertexAuth(loader, project=project)
    transport = FakeVertexTransport(tmp_path / "vertex.json", loader)
    ad = VertexAdapter(auth, transport, state if state is not None else {},
                       RATES, capabilities=dict(CAPS))
    return loader, transport, ad


# ------------------------------------------------------------- auth --

def test_readiness_ok(tmp_path):
    _, _, ad = make(tmp_path)
    st = ad.readiness()
    assert st["ready"] and st["reason"] == "ok"
    assert "access_token" not in str(st)      # token never surfaces


def test_api_key_only_rejected(tmp_path):
    loader, _, ad = make(tmp_path)
    loader.api_key_only()
    ad.auth.refresh()
    assert ad.readiness()["reason"] == "api_key_only"


def test_expired_oauth_named(tmp_path):
    loader, _, ad = make(tmp_path)
    loader.expire()
    ad.auth.refresh()
    assert ad.readiness()["reason"] == "expired"


def test_wrong_project_named(tmp_path):
    loader, _, ad = make(tmp_path)
    loader.switch_project("other-proj")
    ad.auth.refresh()
    assert ad.readiness()["reason"] == "wrong_project"


def test_missing_permission_named(tmp_path):
    loader, _, ad = make(tmp_path)
    loader.revoke_scope()
    ad.auth.refresh()
    assert ad.readiness()["reason"] == "missing_permission"


def test_quota_named(tmp_path):
    loader, _, ad = make(tmp_path)
    loader.set_quota(False)
    ad.auth.refresh()
    assert ad.readiness()["reason"] == "quota_exceeded"


# ---------------------------------------------------------- payload --

def test_payload_matches_pilot_shape(tmp_path):
    _, t, ad = make(tmp_path)
    out = ad.submit(REQ)
    body = t.doc["interactions"][out["operation_id"]]["request"]
    assert body["model"] == "gemini-omni-1.1-flash-preview"
    assert body["background"] is True
    assert body["input"] == [{"type": "text", "text": "checkerboard tank on a hanger"}]
    assert body["response_format"] == [{"type": "video", "aspect_ratio": "9:16",
                                "resolution": "720p", "duration": "4s"}]
    assert body["generation_config"]["video_config"]["task"] == \
        "text_to_video"
    assert "delivery" not in body and "gcs_uri" not in body


def test_unqualified_reference_modes_block(tmp_path):
    _, transport, adapter = make(tmp_path)
    for role in ("image", "video"):
        with pytest.raises(ProviderError, match="input_mode_not_qualified"):
            adapter.submit(dict(REQ, reference_roles={"a1": role}))
    assert not transport.doc["interactions"]


def test_payload_does_not_invent_audio_setting(tmp_path):
    _, transport, adapter = make(tmp_path)
    out = adapter.submit(dict(REQ, native_audio_policy="keep"))
    assert transport.doc["interactions"][out["operation_id"]]["request"]["generation_config"] == {"video_config": {"task": "text_to_video"}}


# --------------------------------------------------------- lifecycle --

def test_submit_observe_download(tmp_path):
    _, _, ad = make(tmp_path)
    out = ad.submit(REQ)
    assert out["status"] == "running"
    ad.observe(out["operation_id"])
    obs = ad.observe(out["operation_id"])
    assert obs["status"] == "succeeded"
    assert obs["reported_usage"]["output_tokens"] == 23168
    assert obs["reported_usage"]["kind"] == "reported_estimate"
    dl = ad.download(out["operation_id"])
    assert base64.b64encode(dl["bytes"]).decode() and dl["sha256"]


def test_http200_terminal_error_parsed(tmp_path):
    _, t, ad = make(tmp_path)
    t.set_fault("http200_terminal")
    out = ad.submit(REQ)                    # accepted: 200 + ID
    ad.observe(out["operation_id"])
    obs = ad.observe(out["operation_id"])
    assert obs["status"] == "failed"
    assert obs["errors"][0]["code"] == "content_filtered"


def test_uri_delivery_terminal_failure(tmp_path):
    """The pilot's confirmed failure: delivery=uri without gcs_uri."""
    _, t, ad = make(tmp_path)
    out = ad.submit(REQ)
    # simulate a request that carried delivery=uri
    it = t.doc["interactions"][out["operation_id"]]
    it["request"]["delivery"] = "uri"
    it["status"], it["errors"] = "failed", [
        {"code": "invalid_request"}]
    t._save()
    obs = ad.observe(out["operation_id"])
    assert obs["status"] == "failed"
    assert obs["errors"][0]["code"] == "invalid_request"


def test_missing_output_not_success(tmp_path):
    _, t, ad = make(tmp_path)
    t.set_fault("missing_output")
    out = ad.submit(REQ)
    ad.observe(out["operation_id"])
    obs = ad.observe(out["operation_id"])
    assert obs["status"] == "failed" and obs["has_media"] is False
    with pytest.raises(ProviderError, match="output_not_available"):
        ad.download(out["operation_id"])


def test_malformed_base64_rejected(tmp_path):
    _, t, ad = make(tmp_path)
    t.set_fault("malformed_b64")
    out = ad.submit(REQ)
    ad.observe(out["operation_id"])
    ad.observe(out["operation_id"])
    with pytest.raises(ProviderError, match="malformed_media"):
        ad.download(out["operation_id"])


def test_same_id_polling_no_new_post(tmp_path):
    _, t, ad = make(tmp_path)
    out = ad.submit(REQ)
    n = len(t.doc["interactions"])
    ad.observe(out["operation_id"])
    ad.observe(out["operation_id"])
    assert len(t.doc["interactions"]) == n   # GETs never create


def test_lost_post_leaves_remote_interaction(tmp_path):
    _, t, ad = make(tmp_path)
    t.lose_next_post()
    with pytest.raises(ProviderError, match="transport_timeout"):
        ad.submit(REQ)
    assert len(t.doc["interactions"]) == 1   # remote accepted anyway


def test_reconcile_by_request_hash(tmp_path):
    _, _, ad = make(tmp_path)
    out = ad.submit(REQ)
    rh = ad._req_hash(REQ, REQ["model"])
    rec = ad.reconcile(request_hash=rh)
    assert rec["operation_id"] == out["operation_id"]


def test_cancel_maps_terminal(tmp_path):
    _, _, ad = make(tmp_path)
    out = ad.submit(REQ)
    with pytest.raises(ProviderError, match="cancel_not_qualified"):
        ad.cancel(out["operation_id"])


# ----------------------------------------------------------- pricing --

def test_usage_estimate_from_dated_rates(tmp_path):
    _, _, ad = make(tmp_path)
    est = ad.estimate(REQ, 4)
    # 103*1.5 + 23168*17.5 + 421*9.0 → 409,383.5 micros → 409384
    assert est["kind"] == "estimate" and est["rates_dated"] == "2026-09-16"
    assert est["usd_micros_est"] == 409384
    m = ad.price(REQ, 4)
    assert (m.unit, m.amount) == ("usd_micros", 511730)


def test_usage_absent_is_null_not_zero(tmp_path):
    _, t, ad = make(tmp_path)
    t.set_fault("missing_output")
    out = ad.submit(REQ)
    ad.observe(out["operation_id"])
    obs = ad.observe(out["operation_id"])
    assert obs["reported_usage"] is None
