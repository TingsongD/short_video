"""M2: scored_ideas output validates; bullets + determinism (test_schema,
test_three_bullets, test_determinism)."""
import json
from pathlib import Path

from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.grill.gate import build_output
from modules.grill.score import score_candidate

FIXTURES = Path(__file__).parent / "fixtures"
CANDIDATES = json.loads((FIXTURES / "grill" / "ideas.json").read_text())["candidates"]
CFG = {"pass_hook_score": 7.0, "pass_virality_score": 6.0, "ideas_per_cluster": 8}

JUDGE = FakeLLM(json.dumps({
    "virality_score": 8.0, "hook_score": 8.5, "payoff_confidence": 8.0,
    "three_bullets": ["beat one", "beat two", "beat three"],
    "judge_notes": "solid",
}))


def test_scored_ideas_schema_valid():
    doc, audit = build_output(
        [dict(c) for c in CANDIDATES], JUDGE, CFG, source_report="data/radar/x.json"
    )
    validate(doc, "scored_ideas.schema.json")
    assert len(audit) == len(CANDIDATES)          # raw judge output logged


def test_passing_ideas_have_exactly_three_bullets():
    doc, _ = build_output([dict(c) for c in CANDIDATES], JUDGE, CFG)
    for idea in doc["ideas"]:
        assert len(idea["three_bullets"]) == 3
        if idea["status"] == "pass":
            assert all(b for b in idea["three_bullets"])


def test_every_kill_has_legible_reason():
    doc, _ = build_output([dict(c) for c in CANDIDATES], JUDGE, CFG)
    for idea in doc["ideas"]:
        if idea["status"] == "kill":
            assert idea["kill_reason"] and len(idea["kill_reason"]) > 5


def test_determinism_same_input_same_scores():
    c = dict(CANDIDATES[0])
    a = score_candidate(c, JUDGE)
    b = score_candidate(c, JUDGE)
    assert a["virality_score"] == b["virality_score"]
    assert a["hook_score"] == b["hook_score"]
    assert JUDGE.calls[0]["temperature"] == 0.0   # temp-0 scoring enforced
