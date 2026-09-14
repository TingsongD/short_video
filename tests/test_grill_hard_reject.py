"""M2: hard-reject rules kill with the right reason (test_hard_reject)."""
import json
from pathlib import Path

from modules.common.llm import FakeLLM
from modules.grill.score import (
    KILL_BAD_NUMBER,
    KILL_NO_HOOK,
    KILL_NO_PAYOFF,
    KILL_NO_VIEWER,
    score_candidate,
)

FIXTURES = Path(__file__).parent / "fixtures"
CANDIDATES = json.loads((FIXTURES / "grill" / "ideas.json").read_text())["candidates"]

GOOD_JUDGE = FakeLLM(json.dumps({
    "virality_score": 8.0, "hook_score": 8.5, "payoff_confidence": 8.0,
    "three_bullets": ["b1", "b2", "b3"], "judge_notes": "ok",
}))


def _score(idea_id):
    c = next(x for x in CANDIDATES if x["idea_id"] == idea_id)
    return score_candidate(c, GOOD_JUDGE)


def test_missing_viewer_killed():
    assert _score("cand-reject-viewer")["kill_reason"] == KILL_NO_VIEWER


def test_unrepayable_hype_hook_killed():
    assert _score("cand-reject-hook")["kill_reason"] == KILL_NO_HOOK


def test_unfilmable_payoff_killed():
    assert _score("cand-reject-filmable")["kill_reason"] == KILL_NO_PAYOFF


def test_unsupported_number_claim_killed():
    assert _score("cand-reject-number")["kill_reason"] == KILL_BAD_NUMBER


def test_clean_candidate_not_hard_rejected():
    scored = _score("cand-pass-1")
    assert scored["status"] == "pending"
    assert scored["kill_reason"] is None
