"""B1 regression: weekly shortlist must run on CONTRACT-shaped grill output
(virality_score/hook_score at top level — no 'scores' dict). Uses the frozen
scored_ideas sample fixture end-to-end through stages.weekly_stages."""
import json
from pathlib import Path

from modules.common.schema import validate
from modules.orchestrate import approval, pipeline, stages
from modules.orchestrate.ledger import CostLedger

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
IDEAS_DOC = json.loads((FIXTURES / "scored_ideas.sample.json").read_text())
LIBRARY_DOC = json.loads((FIXTURES / "format_library.sample.json").read_text())

CFG = {"costs": {"weekly_cap_usd": 25.0}}


def _ctx(tmp_path):
    formats_path = tmp_path / "formats" / "library.json"
    formats_path.parent.mkdir(parents=True)
    formats_path.write_text(json.dumps(LIBRARY_DOC))
    approvals_dir = tmp_path / "approvals"
    approval.grant("spend", approvals_dir)
    return {
        "config": CFG,
        "ledger": CostLedger(path=tmp_path / "ledger.json", weekly_cap=25.0),
        "approvals_dir": approvals_dir,
        "formats_path": formats_path,
        "weekly_dir": tmp_path / "weekly",
        "est": {"llm": 0.05},
        "radar_scan": lambda: {"clusters": [], "degraded": False},
        "grill_run": lambda report: (IDEAS_DOC, []),
    }


def test_weekly_shortlist_runs_on_contract_shaped_ideas(tmp_path):
    rec = pipeline.run_stages("weekly", stages.weekly_stages(_ctx(tmp_path)),
                              log_dir=tmp_path / "runs")
    assert rec["status"] == "ok", rec["stages"]
    assert [s["name"] for s in rec["stages"]] == stages.STAGE_ORDER_WEEKLY

    shortlist = tmp_path / "weekly"
    files = list(shortlist.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    # passing idea listed, ranked by hook_score + virality_score (8.5 + 8.0)
    assert "idea-20260914-001" in text
    assert "16.5" in text
    assert "fmt-dark-list-3" in text
    # killed idea counted, not listed
    assert "1/2 ideas killed" in text


def test_weekly_formats_stage_sorts_by_real_score_fields(tmp_path):
    """Guard against reintroducing a non-contract field like scores.total."""
    ctx = _ctx(tmp_path)
    doc = json.loads(json.dumps(IDEAS_DOC))
    # add a second passing idea with higher combined score -> must rank first
    doc["ideas"].append(dict(
        doc["ideas"][0],
        idea_id="idea-20260914-009", topic="higher scoring topic",
        hook_score=9.0, virality_score=9.0, status="pass", kill_reason=None,
    ))
    ctx["grill_run"] = lambda report: (doc, [])
    rec = pipeline.run_stages("weekly", stages.weekly_stages(ctx),
                              log_dir=tmp_path / "runs")
    assert rec["status"] == "ok", rec["stages"]
    text = next((tmp_path / "weekly").glob("*.md")).read_text()
    assert text.index("idea-20260914-009") < text.index("idea-20260914-001")


def test_grill_fixture_itself_is_contract_valid():
    validate(IDEAS_DOC, "scored_ideas.schema.json")
