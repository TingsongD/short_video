"""Credential failures and recovery: offline provider boundaries only."""
import pytest
from modules.factory.providers.vertex_auth import AuthError, VertexAuth
from modules.factory.testing.fakes import ProviderError
from modules.factory.analysis.vertex import VertexAnalyzer
from modules.factory.execution import Executor
from modules.factory.execution.context import dispatch_context
from modules.factory.store import Database
from modules.factory.testing.authority import approve_operation
from modules.factory.domain.errors import ContractError
from test_factory_api import env


@pytest.fixture
def operation(tmp_path):
    db = Database(tmp_path / "factory.db")
    calls = []
    credentials = {"error": AuthError("reauth_required")}
    def loader():
        if credentials.get("error"):
            raise credentials["error"]
        return {"kind": "oauth", "access_token": "private-token",
                "project": "project", "scopes": ["cloud-platform"]}
    def transport(*args):
        calls.append("POST")
        raise TimeoutError("lost response")
    adapter = VertexAnalyzer(tmp_path / "receipts", None,
        VertexAuth(loader, "project"), "account", "project", "model",
        {"estimate_usd_micros": 1, "reserve_usd_micros": 2,
         "evidence": "offline", "valid_until": "2999-01-01"}, transport=transport)
    executor = Executor(db, adapter)
    request = {"task": "adapt_script", "model": "model"}
    attempt = approve_operation(db, executor, request, "auth-job",
        kind="analysis", provider="analysis", model="model", unit="usd_micros", amount=250000)
    yield db, adapter, executor, attempt, request, credentials, calls
    db.close()


def states(db, attempt):
    from modules.factory.services import FactoryServices
    row = Executor(db).require_request(attempt, {"task": "adapt_script", "model": "model"})
    reservation = next(r for r in FactoryServices(db).reservations() if r["attempt_id"] == attempt)
    return row["status"], row["remote_id"], reservation["status"]


def test_pre_request_auth_failure_is_terminal_and_replay_never_dispatches(operation):
    db, adapter, executor, attempt, request, credentials, calls = operation
    with pytest.raises(ProviderError, match="reauth_required"):
        executor.submit(attempt)
    assert states(db, attempt) == ("failed", None, "released")
    credentials.clear()
    for _ in range(2):
        assert executor.reconcile(attempt)["status"] == "failed"
    assert states(db, attempt) == ("failed", None, "released")
    with dispatch_context({"attempt_id": attempt}):
        assert adapter.submit(request)["status"] == "failed"
    assert calls == []


def test_restart_reconciles_durable_not_sent_proof_without_retry(operation):
    db, adapter, executor, attempt, request, credentials, calls = operation
    # Crash window: adapter persisted failure, executor has not seen it yet.
    db.conn.execute("UPDATE attempts SET status='dispatching' WHERE id=?", (attempt,))
    with dispatch_context({"attempt_id": attempt}), pytest.raises(ProviderError):
        adapter.submit(request)
    credentials.clear()
    assert Executor(db, adapter).reconcile(attempt)["status"] == "failed"
    assert states(db, attempt) == ("failed", None, "released")
    assert calls == []


@pytest.mark.parametrize("conflict", ["attempt_id", "request_hash", "known_remote"])
def test_reconciliation_refuses_conflicting_not_sent_evidence(operation, conflict):
    db, adapter, executor, attempt, request, _, calls = operation
    with dispatch_context({"attempt_id": attempt}), pytest.raises(ProviderError):
        adapter.submit(request)
    with dispatch_context({"attempt_id": attempt}):
        receipt = adapter.reconcile(request_hash="unused")
    if conflict == "known_remote":
        executor.submit(attempt, call=lambda: {"operation_id": "already-accepted", "status": "accepted"})
    else:
        db.conn.execute("UPDATE attempts SET status='dispatching' WHERE id=?", (attempt,))
        receipt["not_sent"][conflict] = "different"
    class ProviderReceipt:
        def reconcile(self, **kwargs):
            return receipt
    with pytest.raises(ContractError, match="not_sent_evidence_mismatch"):
        Executor(db, ProviderReceipt()).reconcile(attempt)
    assert states(db, attempt)[2] == "held"
    assert calls == []


def test_not_sent_exception_without_persisted_proof_keeps_hold(operation):
    from modules.factory.providers.preflight import RequestNotSent
    db, _, executor, attempt, _, _, calls = operation
    def failed():
        raise RequestNotSent("expired")
    with pytest.raises(RequestNotSent):
        executor.submit(attempt, call=failed)
    assert states(db, attempt) == ("unknown", None, "ambiguous")
    assert calls == []


@pytest.mark.parametrize("failure", ["transport", "historical_loader"])
def test_unknown_outcomes_keep_holds_even_after_credentials_recover(operation, failure):
    db, adapter, executor, attempt, request, credentials, calls = operation
    credentials.clear()
    if failure == "historical_loader":
        # Old generic errors carry no evidence of where dispatch stopped.
        with pytest.raises(ProviderError):
            executor.submit(attempt, call=lambda: (_ for _ in ()).throw(ProviderError("loader_failed")))
    else:
        with pytest.raises(ProviderError, match='^analysis_timeout$'):
            executor.submit(attempt)
    executor.reconcile(attempt)
    assert states(db, attempt)[::2] == ("unknown", "ambiguous")
    assert len(calls) == (1 if failure == "transport" else 0)


def test_explicit_provider_recheck_refreshes_credentials_without_dispatch(env, operation):
    client, _, _, services, _ = env
    _, adapter, _, _, _, credentials, calls = operation
    services.providers = {"audiovisual_analysis": adapter}
    assert client.get("/api/providers").json()["audiovisual_analysis"]["detail"]["reason"] == "reauth_required"
    credentials.clear()
    result = client.get("/api/providers?refresh=1").json()["audiovisual_analysis"]
    assert result["authenticated"] is True
    assert calls == []


@pytest.mark.parametrize("reason,expected", [
    ("reauth_required", "Reconnect the configured Google account"),
    ("credential_transport_failed", "network"),
    ("credential_dependency_missing", "Google authentication dependencies"),
    ("loader_failed", "does not prove whether a request was sent"),
])
def test_autorun_api_reports_actionable_recovery(env, reason, expected):
    from modules.factory.autorun.service import AutoRun, AutoRunService
    from modules.factory.domain.records import Job
    client, _, db, services, _ = env
    service = AutoRunService(services)
    run = AutoRun(schema_version="autorun.v1", id="auth-run", created_at="",
                  stage="evidence", state={"evidence_job": "bad-auth"})
    with db.uow() as u:
        u.jobs.put(Job(schema_version="job.v1", id="bad-auth", logical_key="auth", created_at="", status="blocked"))
        u.conn.execute("UPDATE jobs SET blocked_reason=? WHERE id='bad-auth'", (reason,))
        u.records.put(run)
    service.step({"run_id": run.id}, {})
    response = client.get("/api/autoruns/auth-run").json()
    assert expected in str(response)
    assert "Reconcile any unknown attempt before Resume" in str(response)


@pytest.mark.parametrize("case,reason", [
    ("reauth", "reauth_required"),
    ("invalid_grant", "reauth_required"),
    ("refresh", "credential_refresh_failed"),
    ("missing", "no_credentials"),
    ("transport", "credential_transport_failed"),
    ("dependency", "credential_dependency_missing"),
])
def test_credential_readiness_retains_safe_actionable_reason(case, reason):
    # The SDK is optional in offline installations. Core receipt/recovery
    # tests above still run without it; only SDK exception cases need it.
    if case == "dependency":
        error = ModuleNotFoundError("private-token")
    else:
        sdk = pytest.importorskip("google.auth.exceptions")
        error = {
            "reauth": sdk.RefreshError("Reauthentication is needed. private-token"),
            "invalid_grant": sdk.RefreshError("private-token", {"error": "invalid_grant"}),
            "refresh": sdk.RefreshError("private-token", retryable=True),
            "missing": sdk.DefaultCredentialsError("private-token"),
            "transport": sdk.TransportError("private-token"),
        }[case]
    def loader():
        raise error
    auth = VertexAuth(loader, "test-project")
    status = auth.status()
    assert status["reason"] == reason
    assert not status["ready"]
    assert "private-token" not in str(status)
    with pytest.raises(ProviderError) as caught:
        auth.bearer()
    assert caught.value.code == reason
    assert "private-token" not in str(caught.value)
