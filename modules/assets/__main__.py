"""M6 command-line interface; generation always requires a quoted credit ceiling."""
import argparse
import json
import sys
from pathlib import Path
from jsonschema import ValidationError

from modules.common.config import DATA_DIR, secrets, system
from .canvas import CanvasAssets
from .canvas_cli import CanvasCLI, CanvasError
from .manifest import build_manifest, write_manifest
from .pexels import PexelsClient
from .queue import assets_dir, render_cards, validate_shots


def service(config=None, base=None):
    cfg = config if config is not None else system()
    settings = cfg.get("assets", {}).get("jimeng", {})
    cli = CanvasCLI(executable=settings.get("executable", "dreamina-canvas"),
                    profile=settings.get("profile", "default"), region="cn")
    return CanvasAssets(cli, base=base, settings=settings)


def collect(video_id, base=None, fallback="none", pexels=None):
    d = assets_dir(video_id, base)
    sl = validate_shots(json.loads((d / "_shot_list.json").read_text()))
    kinds = {s["idx"]: s["asset_type"] for s in sl["shots"]}
    durations = {s["idx"]: s["duration_s"] for s in sl["shots"]}
    doc = build_manifest(video_id, d, len(sl["shots"]), kinds, durations)
    if fallback == "stock" and doc["missing_shots"]:
        if pexels is None:
            key = secrets().get("PEXELS_API_KEY", "")
            if not key:
                raise ValueError("stock fallback requested but PEXELS_API_KEY is missing")
            pexels = PexelsClient(key)
        for idx in doc["missing_shots"]:
            shot = sl["shots"][idx]
            ext = "png" if shot["asset_type"] == "image" else "mp4"
            pexels.fetch(shot["pexels_fallback_term"], shot["asset_type"],
                         d / f"shot-{idx:02d}.stock.{ext}")
        doc = build_manifest(video_id, d, len(sl["shots"]), kinds, durations)
    write_manifest(doc, d)
    return doc


def main(argv=None):
    p = argparse.ArgumentParser(description="M6 Asset Pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    for name in ("queue", "prepare"):
        parser = sub.add_parser(name)
        parser.add_argument("shot_list")
        if name == "prepare":
            parser.add_argument("--shot", type=int, action="append",
                                help="prepare only this shot (repeatable; useful for a pilot)")
            parser.add_argument("--video-model")
            parser.add_argument("--image-model")
    for name in ("collect", "generate", "status", "resume"):
        parser = sub.add_parser(name)
        parser.add_argument("video_id")
        if name == "collect":
            parser.add_argument("--fallback", choices=["none", "stock"], default="none")
        if name == "generate":
            parser.add_argument("--credit-ceiling", type=int, required=True,
                                help="explicit approval of the prepared batch's total credit ceiling")
        if name in {"generate", "resume"}:
            parser.add_argument("--wait-seconds", type=int, default=45, choices=range(0, 46),
                                metavar="0..45")
    args = p.parse_args(argv)
    try:
        if args.cmd == "queue":
            d = render_cards(json.loads(Path(args.shot_list).read_text()))
            print(f"prompt cards: {d / 'prompt_cards.md'}")
            return 0
        if args.cmd == "collect":
            result = collect(args.video_id, fallback=args.fallback)
        else:
            assets = service()
            if args.cmd == "doctor":
                result = assets.cli.doctor()
                result.pop("userId", None)
                result["models"] = {k: [{"model": i["model"], "aliases": i.get("aliases", [])}
                                        for i in assets.cli.catalog(k)] for k in ("video", "image")}
            elif args.cmd == "prepare":
                for kind in ("video", "image"):
                    value = getattr(args, f"{kind}_model")
                    if value:
                        assets.settings[f"{kind}_model"] = value
                result = assets.prepare(json.loads(Path(args.shot_list).read_text()), args.shot)
            elif args.cmd == "generate":
                result = assets.generate(args.video_id, args.credit_ceiling, args.wait_seconds)
            elif args.cmd == "resume":
                result = assets.resume(args.video_id, args.wait_seconds)
            else:
                result = assets.status(args.video_id)
        print(json.dumps(result, indent=2))
        return 0 if args.cmd in {"doctor", "prepare"} or result.get("complete") else 2
    except ValidationError:
        print("shot list does not match the frozen contract", file=sys.stderr)
        return 2
    except (CanvasError, ValueError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
