"""M8: build mpt_task.json — MoneyPrinterTurbo VideoParams subset.

mpt_task.json sits at data/production/<video_id>/ so relative material paths
are `assets/shot-NN.ext` and audio is `voice.mp3` (MPT resolves them against
the manifest directory, verified against cli.py batch docs).
"""
import json
import math
from pathlib import Path

from modules.common.config import DATA_DIR
from modules.common.schema import validate

MAX_BATCH_TASKS = 100


def build_task(video_id, shot_list, manifest, cfg, video_subject, prepared=None):
    """cfg = system.toml [assembly]. manifest must be complete."""
    if not manifest.get("complete"):
        raise ValueError(
            f"manifest incomplete: missing shots {manifest.get('missing_shots')}"
        )
    task = {
        "video_subject": video_subject or shot_list["hook_line"],
        "video_script": shot_list["script_text"],
        "video_language": "en",
        "video_source": "local",
        "video_materials": ([{"url": m["url"]} for m in prepared["materials"]] if prepared else [
            {"url": f"assets/{a['file']}"}
            for a in sorted(manifest["assets"], key=lambda a: a["shot_idx"])
        ]),
        "custom_audio_file": "voice.mp3",
        "video_aspect": cfg.get("video_aspect", "9:16"),
        "video_count": 1,
        "video_concat_mode": "sequential",
        "video_clip_duration": (prepared["video_clip_duration"] if prepared else
                                math.ceil(max(s["duration_s"] for s in shot_list["shots"]))),
        "subtitle_enabled": True,
        "subtitle_display_mode": cfg.get("subtitle_mode", "word_by_word"),
        "bgm_type": "random",
        "bgm_volume": cfg.get("bgm_volume", 0.15),
        "voice_volume": 1.0,
        "n_threads": 4,
    }
    return validate(task, "mpt_task.schema.json")


def write_task(task, video_dir=None, video_id=None):
    d = Path(video_dir or DATA_DIR / "production" / (video_id or task["video_subject"]))
    d.mkdir(parents=True, exist_ok=True)
    p = d / "mpt_task.json"
    p.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return p


def build_batch(tasks):
    """Batch manifest = JSON array of mpt_task dicts (MPT caps at 100)."""
    if len(tasks) > MAX_BATCH_TASKS:
        raise ValueError(f"batch {len(tasks)} > {MAX_BATCH_TASKS} tasks")
    for t in tasks:
        validate(t, "mpt_task.schema.json")
    return list(tasks)


def write_batch(tasks, path):
    batch = build_batch(tasks)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")
    return p
