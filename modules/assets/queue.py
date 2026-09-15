"""M6: render a shot list into per-shot prompt cards + the assets drop folder.
Lane B (manual) is the supported path: cards are copy-paste ready for Jimeng.
"""
import json
import math
import re
from pathlib import Path

from modules.common.config import DATA_DIR
from modules.common.schema import validate

VIDEO_EXTS = {".mp4", ".mov", ".webm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def assets_dir(video_id, base=None):
    validate_video_id(video_id)
    d = Path(base or DATA_DIR / "production") / video_id / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_video_id(video_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", video_id):
        raise ValueError("video_id must be a single safe folder name")


def validate_shots(shot_list):
    validate(shot_list, "shot_list.schema.json")
    validate_video_id(shot_list["video_id"])
    if [s["idx"] for s in shot_list["shots"]] != list(range(len(shot_list["shots"]))):
        raise ValueError("shot indices must be unique and ordered from zero")
    if any(not math.isfinite(s["duration_s"]) for s in shot_list["shots"]):
        raise ValueError("shot durations must be finite")
    return shot_list


def target_name(shot):
    ext = "png" if shot["asset_type"] == "image" else "mp4"
    return f"shot-{shot['idx']:02d}.{ext}"


def render_cards(shot_list, base=None):
    """Write prompt_cards.md + shot_list copy into the assets dir.
    Returns the assets dir path."""
    validate_shots(shot_list)
    d = assets_dir(shot_list["video_id"], base)
    lines = [
        f"# Jimeng prompt cards — {shot_list['video_id']}",
        "",
        "Drop rendered files into THIS folder as `shot-NN.mp4` / `shot-NN.png`.",
        "Optional source tag: `shot-NN.jimeng.mp4` or `shot-NN.stock.mp4`.",
        "Requirements: video covers the requested duration (at least 3s), min dimension >=720px.",
        "",
    ]
    for s in shot_list["shots"]:
        lines += [
            f"## shot {s['idx']:02d} -> `{target_name(s)}` "
            f"({s['asset_type']}, ~{s['duration_s']}s)",
            "",
            "```",
            s["prompt_jimeng"],
            "```",
            f"Pexels fallback: `{s['pexels_fallback_term']}`",
            "",
        ]
    (d / "prompt_cards.md").write_text("\n".join(lines), encoding="utf-8")
    (d / "_shot_list.json").write_text(
        json.dumps(shot_list, indent=2) + "\n", encoding="utf-8"
    )
    return d
