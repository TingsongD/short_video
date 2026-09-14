"""M3: extraction output validates + no-copy guard (test_extract_schema,
test_no_copy)."""
import json

import pytest

from modules.common.llm import FakeLLM
from modules.formats.extract import draft_format, token_overlap, watch_url

VIDEO = {
    "video_id": "vid_outlier_1", "channel_id": "UCseed1",
    "title": "dark psychology: 3 phrases that control any conversation",
    "views": 6200, "channel_avg": 1000.0, "multiplier": 6.2,
    "subs_ratio": 3.1, "published_at": "2026-09-11T12:00:00Z",
    "format_guess": "listicle",
}

GOOD_LLM = FakeLLM(json.dumps({
    "name": "Dark-facts 3-item listicle",
    "hook_type": "onscreen",
    "beats": [
        "Stakes: name the situation where the viewer is vulnerable",
        "Mechanism: reveal items with one-line explanations",
        "Payoff: give the counter-move or takeaway",
    ],
    "visual_payoff": "items appear as bold on-screen text",
    "cta_pattern": "Follow for part 2",
}))

COPYCAT_LLM = FakeLLM(json.dumps({
    "name": "dark psychology 3 phrases that control any conversation",
    "hook_type": "onscreen",
    "beats": ["dark psychology phrases", "control any conversation",
              "3 phrases that control"],
    "visual_payoff": "x", "cta_pattern": "y",
}))


def test_extract_produces_schema_shaped_entry():
    e = draft_format(VIDEO, "psychology_facts", GOOD_LLM)
    assert e["hook_type"] == "onscreen"
    assert len(e["beats"]) == 3
    assert e["watch_reference"] == watch_url("vid_outlier_1")
    assert e["watch_reference"].startswith("https://")
    assert e["status"] == "candidate"


def test_extract_rejects_copied_wording():
    with pytest.raises(ValueError, match="copies reference"):
        draft_format(VIDEO, "psychology_facts", COPYCAT_LLM)


def test_extract_rejects_bad_hook_type():
    bad = FakeLLM(json.dumps({
        "name": "x", "hook_type": "telepathic",
        "beats": ["a", "b", "c"], "visual_payoff": "v", "cta_pattern": "c",
    }))
    with pytest.raises(ValueError):
        draft_format(VIDEO, "n", bad)


def test_token_overlap_boundaries():
    assert token_overlap("the cat sat", "completely different words") < 0.6
    assert token_overlap("same words here", "same words here") == 1.0
    assert token_overlap("", "anything") == 0.0
