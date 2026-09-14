"""CLI:
  python -m modules.assets queue <shot_list.json>      — write prompt cards
  python -m modules.assets collect <video_id>          — intake + manifest,
        auto Pexels fallback for missing shots (needs PEXELS_API_KEY;
        without it, missing shots are just reported)
Lane A (jimeng_bridge) is best-effort and never invoked unless
JIMENG_BRIDGE_URL is set."""
import argparse
import json
import sys
from pathlib import Path

from modules.common.config import DATA_DIR, secrets
from modules.common.schema import validate

from .manifest import build_manifest, write_manifest
from .pexels import PexelsClient
from .queue import assets_dir, render_cards


def main(argv=None):
    p = argparse.ArgumentParser(description="M6 Asset Pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue")
    q.add_argument("shot_list")
    c = sub.add_parser("collect")
    c.add_argument("video_id")
    args = p.parse_args(argv)

    if args.cmd == "queue":
        sl = json.loads(Path(args.shot_list).read_text())
        d = render_cards(sl)
        print(f"prompt cards -> {d}/prompt_cards.md")
        return 0

    d = assets_dir(args.video_id)
    sl = json.loads((d / "_shot_list.json").read_text())
    kinds = {s["idx"]: s["asset_type"] for s in sl["shots"]}
    doc = build_manifest(args.video_id, d, len(sl["shots"]), kinds)

    key = secrets().get("PEXELS_API_KEY", "")
    if doc["missing_shots"] and key:
        px = PexelsClient(key)
        for idx in list(doc["missing_shots"]):
            shot = sl["shots"][idx]
            ext = "png" if kinds.get(idx) == "image" else "mp4"
            target = d / f"shot-{idx:02d}.stock.{ext}"
            if px.fetch(shot["pexels_fallback_term"], kinds.get(idx, "video"), target):
                print(f"pexels: filled shot {idx} -> {target.name}")
        doc = build_manifest(args.video_id, d, len(sl["shots"]), kinds)
    elif doc["missing_shots"]:
        print(f"missing shots {doc['missing_shots']} (no PEXELS_API_KEY)")

    out = write_manifest(doc, d)
    print(f"manifest: {out} complete={doc['complete']}")
    return 0 if doc["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
