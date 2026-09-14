"""M11 cost ledger: entries append; weekly cap triggers a hard stop BEFORE
the paid call."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from modules.orchestrate.ledger import BudgetExceeded, CostLedger, week_start

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)  # Wednesday


def make_ledger(tmp_path, cap=25.0):
    return CostLedger(path=tmp_path / "ledger.json", weekly_cap=cap)


def test_entries_append_and_persist(tmp_path):
    led = make_ledger(tmp_path)
    led.record("elevenlabs", 0.20, units=420, unit_type="chars",
               video_id="v-1", now=NOW)
    led.record("llm", 0.05, now=NOW)
    reloaded = make_ledger(tmp_path)
    assert [e["service"] for e in reloaded.entries] == ["elevenlabs", "llm"]
    assert reloaded.entries[0]["units"] == 420
    assert reloaded.entries[0]["approved"] is True


def test_weekly_spend_resets_at_week_boundary(tmp_path):
    led = make_ledger(tmp_path)
    led.record("llm", 10.0, now=NOW)                                # this week
    led.record("llm", 10.0, now=NOW - timedelta(days=8))            # last week
    assert led.spent_week(NOW) == pytest.approx(10.0)


def test_cap_blocks_call_that_would_exceed(tmp_path):
    led = make_ledger(tmp_path, cap=0.25)
    led.record("elevenlabs", 0.20, now=NOW)
    led.authorize("llm", 0.05, now=NOW)          # 0.20 + 0.05 == cap: allowed
    with pytest.raises(BudgetExceeded):
        led.authorize("llm", 0.06, now=NOW)      # over cap: hard stop


def test_authorize_uses_this_week_only(tmp_path):
    led = make_ledger(tmp_path, cap=25.0)
    led.record("llm", 24.0, now=NOW - timedelta(days=8))
    led.authorize("elevenlabs", 0.20, now=NOW)   # last week's spend ignored


def test_no_cap_means_unlimited(tmp_path):
    led = CostLedger(path=tmp_path / "l.json", weekly_cap=None)
    led.record("llm", 999.0, now=NOW)
    led.authorize("elevenlabs", 999.0, now=NOW)  # no cap configured


def test_week_start_is_monday_utc():
    wed = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    assert week_start(wed) == datetime(2026, 9, 14, tzinfo=timezone.utc)
