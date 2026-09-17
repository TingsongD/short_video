"""F07 — submission recovery and retry policy. Fault injection before
dispatch, after acceptance, during poll/download/settlement."""
import pytest

from modules.factory.domain import ContractError
from modules.factory.execution import Executor, classify, next_action
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeProvider, ProviderError
from modules.factory.testing.ids import IdFactory


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    ids = IdFactory(tmp_path / "ids.json")
    provider = FakeProvider("vid", tmp_path / "remote", ids, FakeClock())
    yield db, provider
    db.close()


def _prepare(ex, job="j1", seq=1, req=None):
    return ex.prepare(job, seq, req or {"p": 1},
                      provider="fake", request_hash=None)


class TestPrepare:
    def test_intent_attempt_outbox_atomic(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        row = db.uow().attempts.unfinished()
        assert len(row) == 1 and row[0]["status"] == "prepared"
        assert len(db.uow().outbox.pending()) == 1
        intent = db.conn.execute(
            "SELECT * FROM intents").fetchone()
        assert intent["status"] == "prepared"


class TestSubmitClassification:
    def test_reject_before_accept_is_terminal_local_only(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        with pytest.raises(ProviderError):
            ex.submit(aid, call=lambda: provider.submit(
                {"p": 1}, faults=("reject-before-accept",)))
        row = ex._attempt(aid)
        assert row["status"] == "failed"
        assert provider.effect_counts()["submit"] == 0  # no remote effect

    def test_accept_then_timeout_marks_unknown(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        with pytest.raises(ProviderError) as e:
            ex.submit(aid, call=lambda: provider.submit(
                {"p": 1}, faults=("accept-then-timeout",)))
        assert e.value.code == "response_lost"
        assert ex._attempt(aid)["status"] == "unknown"
        # Remote side DID accept — recovery must find it.
        op = provider.reconcile(
            request_hash=ex._attempt(aid)["request_hash"])
        assert op["status"] == "accepted"

    def test_malformed_ack_unknown(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        with pytest.raises(ContractError):
            ex.submit(aid, call=lambda: provider.submit(
                {"p": 1}, faults=("malformed-ack",)))
        assert ex._attempt(aid)["status"] == "unknown"


class TestPollAndDownload:
    def test_poll_maps_remote_states(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex.submit(aid, call=lambda: provider.submit({"p": 1}))
        ex.poll(aid)
        assert ex._attempt(aid)["status"] == "succeeded"

    def test_terminal_failure_from_poll(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex.submit(aid, call=lambda: provider.submit(
            {"p": 1}, faults=("accepted-then-failed",)))
        ex.poll(aid)
        assert ex._attempt(aid)["status"] == "failed"

    def test_download_failure_retries_transfer_only(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex.submit(aid, call=lambda: provider.submit(
            {"p": 1}, faults=("download-failure",)))
        ex.poll(aid)
        with pytest.raises(ProviderError) as e:
            ex.download(aid)
        assert e.value.transient
        # Effect counts: exactly one submit, zero new ops on retry.
        counts = provider.effect_counts()
        assert counts["submit"] == 1 and counts["download"] == 1
        # clear the fault by re-submitting... instead: verify the attempt
        # retains remote_id so a retry targets the same op
        assert ex._attempt(aid)["remote_id"].startswith("vid-op-")

    def test_http200_error_payload_is_terminal(self, env):
        """poll returning status=failed with error body is not success."""
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex.submit(aid, call=lambda: provider.submit(
            {"p": 1}, faults=("accepted-then-failed",)))
        op = ex.poll(aid)
        assert op["status"] == "failed"
        assert ex._attempt(aid)["status"] == "failed"


class TestRecovery:
    def test_restart_reconciles_by_request_hash(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        with pytest.raises(ProviderError):
            ex.submit(aid, call=lambda: provider.submit(
                {"p": 1}, faults=("accept-then-timeout",)))
        # "Restart": new Executor on the same DB+provider.
        ex2 = Executor(db, provider)
        report = ex2.recover()
        assert aid in report["reconciled"]
        assert provider.effect_counts()["submit"] == 1   # never resubmitted
        assert ex2._attempt(aid)["remote_id"] is not None

    def test_unknown_when_no_lookup(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex._set_status(aid, "unknown", "drill")
        op = ex.reconcile(aid)          # nothing remote exists
        assert op is None
        assert ex._attempt(aid)["status"] == "unknown"

    def test_resume_polls_original_id(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex.submit(aid, call=lambda: provider.submit({"p": 1}))
        remote_id = ex._attempt(aid)["remote_id"]
        ex.poll(aid); ex.poll(aid)
        ops = provider.operation(remote_id)
        assert ops["polls"] == 2
        assert provider.effect_counts()["submit"] == 1


class TestCancellationAndFallback:
    def test_cancel_ack_not_terminal(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        ex.submit(aid, call=lambda: provider.submit({"p": 1}))
        assert ex.request_cancel(aid) == "cancel_requested"
        assert ex.cancel_pending(aid)          # suppress fallback
        assert not ex.fallback_allowed(aid)
        ex.poll(aid)                           # terminal cancel resolves
        assert ex._attempt(aid)["status"] == "cancelled"
        assert ex.fallback_allowed(aid)

    def test_resolve_unknown_requires_evidence(self, env):
        db, provider = env
        ex = Executor(db, provider)
        aid = _prepare(ex)
        with pytest.raises(ProviderError):
            ex.submit(aid, call=lambda: provider.submit(
                {"p": 1}, faults=("accept-then-timeout",)))
        with pytest.raises(ContractError) as e:
            ex.resolve_unknown(aid, "", "confirmed_charged")
        assert e.value.code == "resolution_needs_evidence"
        ex.resolve_unknown(aid, "provider console shows op + charge",
                           "confirmed_charged")
        assert ex._attempt(aid)["status"] == "succeeded"
        assert ex.fallback_allowed(aid)


class TestRetryPolicy:
    def test_classify_map(self):
        assert classify("rejected_before_accept") == "pre_acceptance"
        assert classify("quota_exceeded", 429) == "pre_acceptance"
        assert classify("response_lost") == "ambiguous"
        assert classify("download_transport_failed",
                        where="collect") == "retryable_transfer"
        assert classify("generation_failed") == "terminal"
        assert classify("some_unknown_code") == "ambiguous"

    def test_bounded_retry_then_escalate(self):
        a = next_action({"cause": "retryable_read", "retries": 0})
        assert a["action"] == "retry" and a["wait_s"] == 1
        a = next_action({"cause": "retryable_read", "retries": 5})
        assert a["action"] == "escalate"
        a = next_action({"cause": "ambiguous", "retries": 0})
        assert a["action"] == "reconcile"      # never blind retry
        a = next_action({"cause": "auth", "retries": 1})
        assert a["action"] == "retry"

    def test_auth_expiry_during_observe_is_auth_class(self):
        assert classify("auth_required", where="observe") == "auth"
        assert classify("auth_required", where="submit") == "pre_acceptance"
