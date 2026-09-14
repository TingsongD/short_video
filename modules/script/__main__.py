"""CLI: python -m modules.script <scored_ideas.json> <idea_id> [--video-id V]
Needs format library + matches.json + hook bank + LLM keys (Wave 3 spend)."""
import argparse
import json
import sys
from pathlib import Path

from modules.common.config import DATA_DIR, secrets
from modules.common.llm import LLMClient
from modules.formats import library as format_lib
from modules.hooks.select import load_bank, select

from .engine import build_shot_list, save_shot_list


def main(argv=None):
    p = argparse.ArgumentParser(description="M5 Script Engine")
    p.add_argument("scored_ideas")
    p.add_argument("idea_id")
    p.add_argument("--video-id", help="default: v-<idea_id suffix>")
    args = p.parse_args(argv)

    doc = json.loads(Path(args.scored_ideas).read_text())
    idea = next((i for i in doc["ideas"] if i["idea_id"] == args.idea_id), None)
    if not idea or idea["status"] != "pass":
        print(f"idea {args.idea_id} missing or not passed", file=sys.stderr)
        return 1

    lib = format_lib.load(DATA_DIR / "formats" / "library.json")
    matches_p = DATA_DIR / "formats" / "matches.json"
    matches = json.loads(matches_p.read_text()) if matches_p.exists() else {}
    fmt = format_lib.get(lib, matches.get(args.idea_id, {}).get("format_id")
                         or lib["formats"][0]["format_id"])
    hook = select(load_bank(DATA_DIR / "hooks" / "bank.json"),
                  idea["niche"], fmt["hook_type"])
    video_id = args.video_id or f"v-{args.idea_id.removeprefix('idea-')}"

    shot_list = build_shot_list(idea, fmt, hook["text"], video_id,
                                LLMClient.from_secrets(secrets()))
    out = save_shot_list(shot_list)
    print(f"shot_list: {out} ({len(shot_list['shots'])} shots)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
