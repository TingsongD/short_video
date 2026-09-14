"""M2: pass thresholds at exact boundaries (test_threshold)."""
import json

from modules.common.llm import FakeLLM
from modules.grill.gate import apply_gate
from modules.grill.score import score_candidate

CFG = {"pass_hook_score": 7.0, "pass_virality_score": 6.0, "ideas_per_cluster": 8}

CAND = {
    "idea_id": "x1", "niche": "n", "topic": "t",
    "hook_overlay": "a specific repayable hook here",
    "target_viewer": "new parents", "payoff": "a concrete payoff",
    "three_bullets": ["a", "b", "c"], "cta": "follow", "filmable": True,
    "number_claims": [],
}


def _llm(hook, virality):
    return FakeLLM(json.dumps({
        "virality_score": virality, "hook_score": hook,
        "payoff_confidence": 7.0, "three_bullets": ["a", "b", "c"],
        "judge_notes": "",
    }))


def test_hook_69_killed():
    idea = apply_gate(score_candidate(CAND, _llm(6.9, 8.0)), CFG)
    assert idea["status"] == "kill"
    assert "hook_score" in idea["kill_reason"]


def test_hook_70_passes():
    idea = apply_gate(score_candidate(CAND, _llm(7.0, 8.0)), CFG)
    assert idea["status"] == "pass"
    assert idea["kill_reason"] is None


def test_virality_59_killed():
    idea = apply_gate(score_candidate(CAND, _llm(9.0, 5.9)), CFG)
    assert idea["status"] == "kill"
    assert "virality_score" in idea["kill_reason"]


def test_virality_60_passes():
    idea = apply_gate(score_candidate(CAND, _llm(7.0, 6.0)), CFG)
    assert idea["status"] == "pass"
