"""M5: script length bounds + hook-first rule (test_length)."""
import json
from pathlib import Path

import pytest

from modules.common.llm import FakeLLM
from modules.script.write import validate_script, word_count, write_script

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SAMPLE = json.loads((FIXTURES / "shot_list.sample.json").read_text())
HOOK = SAMPLE["hook_line"]
SCRIPT = SAMPLE["script_text"]

IDEA = {"idea_id": "idea-20260914-001", "topic": "t", "payoff": "p",
        "three_bullets": ["a", "b", "c"], "cta": "follow"}
FMT = {"format_id": "fmt-x", "name": "f", "beats": ["b1", "b2", "b3"],
       "cta_pattern": "follow"}


def test_word_bounds_constants():
    assert 60 <= word_count(SCRIPT) <= 110


def test_hook_is_first_sentence():
    assert validate_script(SCRIPT, HOOK) == SCRIPT


def test_too_short_rejected():
    with pytest.raises(ValueError, match="words"):
        validate_script(HOOK + " Short body. Tiny payoff.", HOOK)


def test_hook_not_first_rejected():
    with pytest.raises(ValueError, match="first sentence"):
        validate_script("Warmup line first. " + SCRIPT, HOOK)


def test_write_script_validates_llm_output():
    assert write_script(IDEA, FMT, HOOK, FakeLLM(SCRIPT)) == SCRIPT
    with pytest.raises(ValueError):
        write_script(IDEA, FMT, HOOK, FakeLLM("no hook here. too short."))
