"""CLI:
  python -m modules.formats seed <niche_report.json>   — LLM-extract formats
  python -m modules.formats match <scored_ideas.json>  — write matches.json
LLM-backed seeding needs keys (Wave 3); match is offline."""
import argparse
import json
import sys
from pathlib import Path

from modules.common.config import DATA_DIR, secrets, system
from modules.common.llm import LLMClient
from modules.common.schema import validate

from . import library
from .extract import draft_format
from .match import match_ideas

LIB = DATA_DIR / "formats" / "library.json"


def main(argv=None):
    p = argparse.ArgumentParser(description="M3 Format Library")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="extract formats from a niche report")
    s.add_argument("report")
    m = sub.add_parser("match", help="match passing ideas to formats")
    m.add_argument("scored_ideas")
    args = p.parse_args(argv)

    lib = library.load(LIB)
    if args.cmd == "seed":
        report = json.loads(Path(args.report).read_text())
        llm = LLMClient.from_secrets(secrets())
        added = 0
        for entry in report.get("niches", []):
            for v in entry.get("breakout_videos", []):
                try:
                    fmt = draft_format(v, entry["niche"], llm)
                    library.add(lib, fmt)
                    added += 1
                except ValueError as e:
                    print(f"  skip {v['video_id']}: {e}", file=sys.stderr)
        library.save(lib, LIB)
        print(f"seeded {added} formats -> {LIB}")
    else:
        doc = json.loads(Path(args.scored_ideas).read_text())
        matches = match_ideas(doc["ideas"], lib["formats"])
        out = DATA_DIR / "formats" / "matches.json"
        out.write_text(json.dumps(matches, indent=2) + "\n", encoding="utf-8")
        print(f"{len(matches)} ideas matched -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
