"""M2: cluster expansion via LLM produces normalized candidates."""
import json

from modules.common.llm import FakeLLM
from modules.grill.generate import expand_cluster

CLUSTER = {
    "niche": "psychology_facts", "cluster_size": 2, "confirmed": True,
    "breakout_videos": [
        {"video_id": "v1", "title": "dark psychology: 3 phrases",
         "multiplier": 6.2, "views": 6200, "format_guess": "listicle"},
        {"video_id": "v2", "title": "dark psychology signs",
         "multiplier": 8.0, "views": 6000, "format_guess": "listicle"},
    ],
}

LLM = FakeLLM(json.dumps([
    {
        "topic": "3 phrases manipulators use",
        "hook_overlay": "If someone says these 3 phrases, walk away.",
        "target_viewer": "18-34 self-protection viewers",
        "payoff": "the phrases + counters",
        "three_bullets": ["a", "b", "c"],
        "cta": "follow", "number_claims": [],
    },
    {
        "topic": "signs of covert control",
        "hook_overlay": "3 signs someone is steering the conversation.",
        "target_viewer": "relationship viewers",
        "payoff": "spot steering tactics",
        "three_bullets": ["d", "e", "f"],
        "cta": "follow", "number_claims": [],
    },
]))


def test_expand_cluster_returns_candidates():
    ideas = expand_cluster(CLUSTER, LLM, n_ideas=8)
    assert len(ideas) == 2
    for i in ideas:
        assert i["niche"] == "psychology_facts"
        assert i["source_video_ids"] == ["v1", "v2"]
        assert i["filmable"] is True


def test_expand_caps_at_n_ideas():
    assert len(expand_cluster(CLUSTER, LLM, n_ideas=1)) == 1


def test_generate_prompt_mentions_niche_and_evidence():
    expand_cluster(CLUSTER, LLM, n_ideas=8)
    assert "psychology_facts" in LLM.calls[0]["user"]
    assert "dark psychology" in LLM.calls[0]["user"]
