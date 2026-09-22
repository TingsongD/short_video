"""Expected technical failures should be actionable, not traceback-shaped."""
import pytest
from test_factory_api import env
from modules.factory.autorun.service import AutoRun
from modules.factory.domain.errors import ContractError


@pytest.mark.parametrize("code", ["review_proxy_failed", "review_proxy_too_large",
                                  "review_proxy_mismatch", "review_proxy_quality_limit"])
def test_final_review_copy_failure_has_safe_specific_recovery(env, monkeypatch, code):
    client, _, _, services, _ = env
    services.autorun._put(AutoRun(id="qc-recovery", stage="final_qc"))
    def fail(run):
        raise ContractError(code, "artifact_id", "Local review preparation failed")
    monkeypatch.setattr(services.autorun, "_drive", fail)
    services.autorun.step({"run_id": "qc-recovery"}, None)
    run = services.autorun.get("qc-recovery")
    assert run.status == "paused"
    assert run.pause["code"] == code
    assert "Traceback" not in run.pause["detail"]
    assert "service.py" not in run.pause["detail"]
    assert "original" in run.pause["detail"].lower()
    assert "Resume" in run.pause["action"]
    assert "review copy" in run.pause["action"].lower()
