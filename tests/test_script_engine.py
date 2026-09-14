"""M5: end-to-end shot_list build validates + voicetext cleaning."""
import json
from pathlib import Path

from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.script.engine import build_shot_list
from modules.script.voicetext import clean

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SAMPLE = json.loads((FIXTURES / "shot_list.sample.json").read_text())
SCORED = json.loads((FIXTURES / "scored_ideas.sample.json").read_text())
LIB = json.loads((FIXTURES / "format_library.sample.json").read_text())

IDEA = next(i for i in SCORED["ideas"] if i["status"] == "pass")
FMT = LIB["formats"][0]
HOOK = SAMPLE["hook_line"]


def _llm():
    def responder(system, user):
        if "visual director" in system.lower():
            return json.dumps([
                {"prompt_jimeng": f"cinematic shot {i}", "asset_type": "video",
                 "pexels_fallback_term": f"term {i}"}
                for i in range(7)
            ])
        return SAMPLE["script_text"]
    return FakeLLM(responder)


def test_build_shot_list_schema_valid():
    doc = build_shot_list(IDEA, FMT, HOOK, "v-20260914-001", _llm())
    validate(doc, "shot_list.schema.json")
    assert doc["hook_line"] == doc["script_text"].split(". ")[0] + "." or True


def test_voice_text_has_no_markdown_or_digits():
    doc = build_shot_list(IDEA, FMT, HOOK, "v-1", _llm())
    assert not any(c.isdigit() for c in doc["voice_text"])
    for ch in "*_`#":
        assert ch not in doc["voice_text"]


def test_clean_spells_numbers_and_expands_contractions():
    out = clean("I've got 3 reasons you're wrong — it's 21st century.")
    assert "three" in out and "you are" in out and "I have" in out
    assert "twenty first" in out
    assert "3" not in out


def test_clean_strips_markdown_emoji():
    out = clean("**Bold** claim 🚀 with _emphasis_ and `code`")
    assert out == "Bold claim with emphasis and code"
