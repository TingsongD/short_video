"""M5: shot splitting, durations, hook-first, fallbacks (test_beats,
test_hook_first, test_fallback)."""
import json
from pathlib import Path

from modules.common.llm import FakeLLM
from modules.script.shots import WORDS_PER_SEC, assign_visuals, split_shots
from modules.script.write import word_count

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SAMPLE = json.loads((FIXTURES / "shot_list.sample.json").read_text())
HOOK, SCRIPT = SAMPLE["hook_line"], SAMPLE["script_text"]


def test_four_to_seven_shots():
    shots = split_shots(SCRIPT, HOOK)
    assert 4 <= len(shots) <= 7


def test_durations_track_voice_estimate():
    shots = split_shots(SCRIPT, HOOK)
    est = word_count(SCRIPT) / WORDS_PER_SEC
    total = sum(s["duration_s"] for s in shots)
    assert abs(total - est) / est <= 0.20


def test_hook_shot_is_video_at_idx_zero():
    shots = assign_visuals(split_shots(SCRIPT, HOOK), llm=None)
    assert shots[0]["idx"] == 0
    assert shots[0]["asset_type"] == "video"


def test_every_shot_has_fallback_term():
    for s in assign_visuals(split_shots(SCRIPT, HOOK), llm=None):
        assert s["pexels_fallback_term"].strip()
        assert s["prompt_jimeng"].strip()


def test_llm_visuals_used_when_valid():
    n = len(split_shots(SCRIPT, HOOK))
    visuals = json.dumps([
        {"prompt_jimeng": f"custom prompt {i}", "asset_type": "image",
         "pexels_fallback_term": f"term {i}"}
        for i in range(n)
    ])
    shots = assign_visuals(split_shots(SCRIPT, HOOK), FakeLLM(visuals))
    assert shots[0]["asset_type"] == "video"      # forced even when LLM says image
    assert shots[1]["asset_type"] == "image"
    assert shots[1]["prompt_jimeng"] == "custom prompt 1"


def test_bad_llm_output_falls_back_to_template():
    shots = assign_visuals(split_shots(SCRIPT, HOOK), FakeLLM("not json"))
    assert all(s["pexels_fallback_term"] for s in shots)
