"""M5 orchestrator: (idea, format_entry, hook) -> validated shot_list doc."""
import json
from pathlib import Path

from modules.common.config import DATA_DIR
from modules.common.schema import validate

from .shots import assign_visuals, split_shots
from .voicetext import clean
from .write import write_script


def build_shot_list(idea, format_entry, hook_text, video_id, llm):
    """llm is used for both script writing and visual direction."""
    script = write_script(idea, format_entry, hook_text, llm)
    shots = assign_visuals(split_shots(script, hook_text), llm)
    doc = {
        "video_id": video_id,
        "idea_id": idea["idea_id"],
        "format_id": format_entry["format_id"],
        "script_text": script,
        "hook_line": hook_text,
        "voice_text": clean(script),
        "subtitle_lang": "en",
        "shots": [
            {
                "idx": s["idx"],
                "duration_s": s["duration_s"],
                "prompt_jimeng": s["prompt_jimeng"],
                "asset_type": s["asset_type"],
                "pexels_fallback_term": s["pexels_fallback_term"],
            }
            for s in shots
        ],
    }
    return validate(doc, "shot_list.schema.json")


def save_shot_list(doc, out_dir=None):
    d = Path(out_dir or DATA_DIR / "production") / doc["video_id"]
    d.mkdir(parents=True, exist_ok=True)
    p = d / "shot_list.json"
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p
