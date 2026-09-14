"""M3: every passing idea gets exactly one default format (test_match)."""
import json
from pathlib import Path

import pytest

from modules.formats.match import match_ideas

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
LIB = json.loads((FIXTURES / "format_library.sample.json").read_text())
IDEAS = json.loads((FIXTURES / "scored_ideas.sample.json").read_text())["ideas"]


def test_pass_idea_gets_default_format():
    m = match_ideas(IDEAS, LIB["formats"])
    passing = [i for i in IDEAS if i["status"] == "pass"]
    assert set(m) == {i["idea_id"] for i in passing}
    assert m["idea-20260914-001"]["format_id"] == "fmt-dark-list-3"


def test_alt_format_labeled_when_available():
    formats = LIB["formats"] + [{
        "format_id": "fmt-alt", "name": "alt", "hook_type": "spoken",
        "beats": ["a", "b", "c"], "visual_payoff": "v", "cta_pattern": "c",
        "watch_reference": "https://x.co/v", "status": "candidate",
        "our_stats": {"videos": 0, "wins": 0}, "niche": "other",
    }]
    m = match_ideas(IDEAS, formats)
    assert m["idea-20260914-001"]["alt_format_id"] == "fmt-alt"


def test_proven_format_beats_candidate_same_niche():
    formats = [dict(LIB["formats"][0]), {
        "format_id": "fmt-proven", "name": "p", "hook_type": "spoken",
        "beats": ["a", "b", "c"], "visual_payoff": "v", "cta_pattern": "c",
        "watch_reference": "https://x.co/v", "status": "proven",
        "our_stats": {"videos": 5, "wins": 3}, "niche": "psychology_facts",
    }]
    m = match_ideas(IDEAS, formats)
    assert m["idea-20260914-001"]["format_id"] == "fmt-proven"


def test_retired_format_never_matches():
    retired = [dict(LIB["formats"][0], status="retired")]
    with pytest.raises(ValueError):
        match_ideas(IDEAS, retired)


def test_empty_library_raises():
    with pytest.raises(ValueError):
        match_ideas(IDEAS, [])
