"""CLI:
  python -m modules.publish meta <scored_ideas.json> <idea_id>  — LLM metadata
  python -m modules.publish record <video_id> --youtube-id ID --idea ID \
      --format FMT --niche N [--title T --caption C --hashtags a,b]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from modules.common.config import DATA_DIR, secrets, system
from modules.common.llm import LLMClient
from modules.formats import library as format_lib

from .metadata import build_metadata
from .record import CadenceBlock, check_cadence, load_records, write_record
from .uploader import manual_instructions


def main(argv=None):
    p = argparse.ArgumentParser(description="M9 Publishing")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("meta")
    m.add_argument("scored_ideas")
    m.add_argument("idea_id")
    r = sub.add_parser("record")
    r.add_argument("video_id")
    r.add_argument("--youtube-id", required=True)
    r.add_argument("--idea", required=True)
    r.add_argument("--format", required=True)
    r.add_argument("--niche", required=True)
    r.add_argument("--title", default="")
    r.add_argument("--caption", default="")
    r.add_argument("--hashtags", default="")
    args = p.parse_args(argv)

    cfg = system()["publish"]

    if args.cmd == "meta":
        doc = json.loads(Path(args.scored_ideas).read_text())
        idea = next(i for i in doc["ideas"] if i["idea_id"] == args.idea_id)
        lib = format_lib.load(DATA_DIR / "formats" / "library.json")
        fmt = lib["formats"][0]
        meta = build_metadata(idea, fmt, LLMClient.from_secrets(secrets()))
        print(json.dumps(meta, indent=2))
        return 0

    records = load_records()
    try:
        check_cadence(records, "youtube", max_per_day=cfg["max_posts_per_day"])
    except CadenceBlock as e:
        print(f"blocked: {e}", file=sys.stderr)
        return 2
    record = {
        "video_id": args.video_id,
        "platform_video_ids": {"youtube": args.youtube_id},
        "title": args.title or args.video_id,
        "caption": args.caption,
        "hashtags": [h for h in args.hashtags.split(",") if h],
        "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "format_id": args.format,
        "idea_id": args.idea,
        "niche": args.niche,
        "variant_index": 1,
    }
    out = write_record(record)
    print(f"publish_record: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
