"""M11 pipeline order: produce stages run in order; a failed gate stops the
run; every run writes a record to logs/runs/."""
import json
from pathlib import Path

import pytest

from modules.orchestrate import pipeline, stages


def test_stages_run_in_order(tmp_path):
    calls = []
    st = [(f"s{i}", lambda i=i: calls.append(i)) for i in range(4)]
    rec = pipeline.run_stages("produce", st, log_dir=tmp_path)
    assert calls == [0, 1, 2, 3]
    assert rec["status"] == "ok"
    assert [s["name"] for s in rec["stages"]] == ["s0", "s1", "s2", "s3"]


def test_failed_gate_stops_remaining_stages(tmp_path):
    calls = []

    def boom():
        calls.append(2)
        raise RuntimeError("qc failed")

    st = [("a", lambda: calls.append(0)), ("b", lambda: calls.append(1)),
          ("qc", boom), ("d", lambda: calls.append(3))]
    rec = pipeline.run_stages("produce", st, log_dir=tmp_path)
    assert calls == [0, 1, 2]                    # d never ran
    assert rec["status"] == "failed"
    assert rec["failed_at"] == "qc"
    assert "qc failed" in rec["stages"][2]["error"]


def test_run_record_written_per_run(tmp_path):
    rec = pipeline.run_stages("weekly", [], log_dir=tmp_path)
    p = Path(rec["log_path"])
    assert p.exists() and p.parent == tmp_path
    saved = json.loads(p.read_text())
    assert saved["cmd"] == "weekly" and saved["status"] == "ok"


def test_produce_stage_names_match_spec():
    assert stages.STAGE_ORDER_PRODUCE == [
        "hook", "script", "assets", "voice", "assemble", "qc", "publish"]
    assert stages.STAGE_ORDER_WEEKLY == ["radar", "grill", "formats"]
    assert stages.STAGE_ORDER_READBACK == ["due", "pull", "record"]


def test_find_idea_rejects_non_passing(tmp_path):
    g = tmp_path / "grill"
    g.mkdir()
    (g / "2026-09-14.json").write_text(json.dumps({
        "ideas": [{"idea_id": "i-1", "status": "kill"},
                  {"idea_id": "i-2", "status": "pass", "niche": "n"}]}))
    with pytest.raises(ValueError, match="kill"):
        stages.find_idea("i-1", g)
    assert stages.find_idea("i-2", g)["niche"] == "n"
    with pytest.raises(KeyError):
        stages.find_idea("i-missing", g)
