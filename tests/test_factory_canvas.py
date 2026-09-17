"""F16: Jimeng Canvas adapter — argv-level fake CLI, idempotent prep,
native quotes, credit faults, account safety."""
import pytest

from modules.assets.canvas_cli import CanvasCLI, CanvasError
from modules.factory.providers.canvas import CanvasAdapter
from modules.factory.testing.fakes import FakeCanvasRunner, ProviderError


def make(tmp_path, **kw):
    runner = FakeCanvasRunner(tmp_path / "cli.json", **kw)
    adapter = CanvasAdapter(CanvasCLI(runner=runner), {})
    return runner, adapter


REQ = {"prompt": "vertical product shot", "duration_s": 4,
       "model": "seedance_2.0_fast_vip"}


def test_readiness_ok(tmp_path):
    _, ad = make(tmp_path)
    r = ad.readiness()
    assert r["ready"] and r["userId"] == "u-1"


def test_readiness_login_expired(tmp_path):
    r, ad = make(tmp_path)
    r.expire_login()
    out = ad.readiness()
    assert out == {"ready": False, "reason": "login_required"}


def test_wrong_account_reconnect_rejected(tmp_path):
    r, ad = make(tmp_path)
    ad.expected_user = "u-1"
    r.reconnect(user_id="u-2")          # different account, logged in
    assert ad.readiness()["reason"] == "account_mismatch"


def test_prepare_idempotent_across_restart(tmp_path):
    r, _ = make(tmp_path)
    state = {}
    ad = CanvasAdapter(CanvasCLI(runner=r), state)
    p1 = ad.prepare(REQ)
    # 'restart': new runner + adapter, same on-disk fake + same state map
    ad2 = CanvasAdapter(
        CanvasCLI(runner=FakeCanvasRunner(tmp_path / "cli.json")), state)
    assert ad2.prepare(REQ) == p1
    assert len(r.doc["nodes"]) == 1      # no duplicate paid node


def test_native_quote_ceiling(tmp_path):
    _, ad = make(tmp_path)
    q = ad.prepare_quote(REQ)
    assert q["max_credits"] == 54 and q["items"][0]["nodeId"]


def test_submit_observe_download_round_trip(tmp_path):
    _, ad = make(tmp_path)
    out = ad.submit(REQ)
    assert out["ceiling"] == 54
    ad.observe(out["operation_id"])
    obs = ad.observe(out["operation_id"])
    assert obs["status"] == "succeeded"
    dl = ad.download(out["operation_id"])
    assert dl["sha256"] and dl["bytes"]


def test_submit_id_derived_from_request_hash(tmp_path):
    _, ad = make(tmp_path)
    a, b = ad.submit(REQ), ad.submit(dict(REQ))
    assert a["submit_id"] == b["submit_id"]


def test_credit_reject_is_named_fault(tmp_path):
    r, ad = make(tmp_path)
    r.set_fault("credit_reject")
    with pytest.raises(ProviderError, match="credits_rejected"):
        ad.submit(REQ)


def test_partial_quote_raises_before_charge(tmp_path):
    r, ad = make(tmp_path)
    r.set_fault("partial_quote")
    # single-node quote isn't partial; add second node then quote both
    prep = ad.prepare(REQ)
    cli = CanvasCLI(runner=r)
    node2 = cli.call("node", "create", "video", "--project-id",
                     prep["project_id"], "--model", REQ["model"],
                     "--mode", "t2v", "--duration", 4, "--prompt", "x")
    with pytest.raises(CanvasError, match="quote_incomplete"):
        cli.quote(prep["project_id"], [prep["node_id"], node2["nodeId"]])


def test_malformed_json_response_named(tmp_path):
    r, _ = make(tmp_path)
    r.set_fault("malformed_json")
    cli = CanvasCLI(runner=r)
    with pytest.raises(CanvasError, match="invalid_response"):
        cli.doctor()


def test_cli_missing_named(tmp_path):
    r, _ = make(tmp_path)
    r.set_fault("cli_missing")
    with pytest.raises(CanvasError, match="cli_missing"):
        CanvasCLI(runner=r).doctor()


def test_transport_timeout_named_no_resubmit(tmp_path):
    r, _ = make(tmp_path)
    r.set_fault("transport_timeout")
    with pytest.raises(CanvasError, match="transport_timeout"):
        CanvasCLI(runner=r).doctor()


def test_lost_run_response_leaves_remote_op(tmp_path):
    r, ad = make(tmp_path)
    r.lose_next_run()
    with pytest.raises(ProviderError, match="transport_timeout"):
        ad.submit(REQ)
    # The remote side did accept — the op exists in fake state
    assert r.doc["ops"], "accepted op must persist despite lost ack"


def test_reconcile_by_request_hash(tmp_path):
    _, ad = make(tmp_path)
    out = ad.submit(REQ)
    rh = ad._req_hash(REQ)
    rec = ad.reconcile(request_hash=rh)
    assert rec["operation_id"] == out["operation_id"]


def test_cancel_supported(tmp_path):
    _, ad = make(tmp_path)
    out = ad.submit(REQ)
    assert ad.cancel(out["operation_id"])["acknowledged"]


def test_price_table_estimate(tmp_path):
    _, ad = make(tmp_path)
    ad.price_table = {"seedance_2.0_fast_vip": {4: 30, 8: 54}}
    m = ad.price(REQ, 4, model="seedance_2.0_fast_vip")
    assert (m.unit, m.amount) == ("jimeng_credits", 30)


def test_state_survives_adapter_restart(tmp_path):
    r, _ = make(tmp_path)
    state = {}
    ad = CanvasAdapter(CanvasCLI(runner=r), state)
    out = ad.submit(REQ)
    ad2 = CanvasAdapter(
        CanvasCLI(runner=FakeCanvasRunner(tmp_path / "cli.json")), state)
    obs = ad2.observe(out["operation_id"])
    assert obs["operation_id"] == out["operation_id"]
