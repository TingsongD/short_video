"""M11 approval gate: no paid call executes without an approval token —
checked BEFORE the callable runs."""
from datetime import datetime, timedelta, timezone

import pytest

from modules.orchestrate import approval, stages
from modules.orchestrate.ledger import CostLedger

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def test_unapproved_paid_call_never_runs(tmp_path):
    calls = []
    led = CostLedger(path=tmp_path / "l.json", weekly_cap=25.0)
    with pytest.raises(approval.ApprovalDenied):
        stages.paid_call(led, "elevenlabs", 0.20,
                         lambda: calls.append("called"),
                         lambda r: (0.20, {}),
                         approvals_dir=tmp_path / "appr")
    assert calls == []                  # vendor never invoked
    assert led.entries == []            # nothing logged


def test_approved_token_allows_call_and_logs(tmp_path):
    appr = tmp_path / "appr"
    approval.grant("spend", appr, now=NOW)
    led = CostLedger(path=tmp_path / "l.json", weekly_cap=25.0)
    out = stages.paid_call(led, "elevenlabs", 0.20,
                           lambda: "audio-bytes",
                           lambda r: (0.20, {"units": 10}),
                           approvals_dir=appr)
    assert out == "audio-bytes"
    assert led.entries[0]["service"] == "elevenlabs"
    assert led.entries[0]["approved"] is True


def test_env_flag_approves(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_APPROVE", "1")
    assert approval.is_approved("spend", tmp_path / "nonexistent")


def test_expired_token_denies(tmp_path):
    appr = tmp_path / "appr"
    p = approval.grant("spend", appr, ttl_hours=1, now=NOW)
    later = NOW + timedelta(hours=2)
    assert not approval.is_approved("spend", appr, now=later)


def test_tty_prompt_can_grant(tmp_path):
    appr = tmp_path / "appr"
    approval.require("spend", "test", appr, prompter=lambda q: "y", now=NOW)
    assert approval.is_approved("spend", appr, now=NOW)


def test_tty_prompt_decline_denies(tmp_path):
    with pytest.raises(approval.ApprovalDenied):
        approval.require("spend", "test", tmp_path / "appr",
                         prompter=lambda q: "n", now=NOW)


def test_over_cap_blocks_before_approval(tmp_path):
    led = CostLedger(path=tmp_path / "l.json", weekly_cap=0.10)
    approval.grant("spend", tmp_path / "appr", now=NOW)
    calls = []
    from modules.orchestrate.ledger import BudgetExceeded
    with pytest.raises(BudgetExceeded):
        stages.paid_call(led, "llm", 0.20, lambda: calls.append(1),
                         lambda r: (0.20, {}),
                         approvals_dir=tmp_path / "appr")
    assert calls == []
