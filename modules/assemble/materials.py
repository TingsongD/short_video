"""Validate coverage and render ordered clips to measured narration timing."""
import hashlib
import json
import math
import subprocess
from pathlib import Path

from modules.assets.intake import probe, validate_file
from modules.assets.queue import validate_shots
from modules.common.schema import validate
from .qc import probe_full


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def narration_duration(path):
    data = probe_full(path)
    if not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise ValueError("narration has no audio stream")
    seconds = float(data.get("format", {}).get("duration") or 0)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("narration duration is invalid")
    return seconds


def allocations(shots, seconds, fps=30):
    weights = [float(s["duration_s"]) for s in shots]
    if (not weights or any(not math.isfinite(w) or w <= 0 for w in weights)
            or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError("shot and narration durations must be positive and finite")
    frames = math.ceil(seconds * fps)
    boundaries = [0]
    cumulative = 0
    for weight in weights:
        cumulative += weight
        boundaries.append(round(cumulative / sum(weights) * frames))
    counts = [b - a for a, b in zip(boundaries, boundaries[1:])]
    if min(counts) < 1:
        raise ValueError("narration is too short for this shot list")
    return [n / fps for n in counts]


def prepare_clips(video_dir, shot_list, manifest, resolution=(1080, 1920),
                  runner=None):
    runner = runner or subprocess.run
    validate_shots(shot_list)
    validate(manifest, "asset_manifest.schema.json")
    shots = shot_list["shots"]
    entries = manifest["assets"]
    if (manifest["video_id"] != shot_list["video_id"] or not manifest.get("complete")
            or len(entries) != len(shots)
            or {e["shot_idx"] for e in entries} != {s["idx"] for s in shots}):
        raise ValueError("manifest must cover every shot exactly once")
    entries = {e["shot_idx"]: e for e in entries}
    directory = Path(video_dir).resolve()
    voice = directory / "voice.mp3"
    seconds = narration_duration(voice)
    durations = allocations(shots, seconds)
    plans = []
    for shot, duration in zip(shots, durations):
        entry = entries[shot["idx"]]
        path = (directory / "assets" / entry["file"]).resolve()
        if not path.is_relative_to(directory / "assets"):
            raise ValueError("asset path escapes its folder")
        if entry["kind"] != shot["asset_type"]:
            raise ValueError(f"shot {shot['idx']}: media type mismatch")
        ok, info = validate_file(path, entry["kind"], max(shot["duration_s"], duration))
        if not ok:
            raise ValueError(f"shot {shot['idx']} cannot cover {duration:.3f}s: {info}")
        plans.append({"idx": shot["idx"], "source": str(path), "kind": entry["kind"],
                      "duration_s": duration, "source_sha256": file_hash(path)})
    # Finish all preflight checks before rendering any clip.
    width, height = resolution
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("output dimensions must be positive even integers")
    identity = {"shots": shot_list, "sources": plans, "voice_sha256": file_hash(voice),
                "resolution": list(resolution), "fps": 30, "version": 1}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    dest = directory / "prepared"
    receipt_path = dest / "materials.json"
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text())
            if receipt.get("fingerprint") == digest and len(receipt["materials"]) == len(plans):
                for item, plan in zip(receipt["materials"], plans):
                    path = (directory / item["url"]).resolve()
                    info = probe(path)
                    if (not path.is_relative_to(dest) or file_hash(path) != item["sha256"]
                            or info["kind"] != "video" or (info["width"], info["height"]) != resolution
                            or abs(info["duration_s"] - plan["duration_s"]) > 0.04):
                        break
                else:
                    return receipt
        except (KeyError, ValueError, OSError, RuntimeError, TypeError):
            pass
    dest.mkdir(parents=True, exist_ok=True)
    materials = []
    for plan in plans:
        path = dest / f"shot-{plan['idx']:02d}.mp4"
        temp = path.with_suffix(".part.mp4")
        args = ["ffmpeg", "-y", "-v", "error", "-xerror"]
        if plan["kind"] == "image":
            args += ["-loop", "1", "-framerate", "30"]
        args += ["-i", plan["source"], "-map", "0:v:0", "-an", "-sn",
                 "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},setsar=1,fps=30",
                 "-frames:v", str(round(plan["duration_s"] * 30)),
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp)]
        result = runner(args, capture_output=True, text=True, timeout=300)
        if result.returncode:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"shot {plan['idx']} failed decoding or clip preparation")
        info = probe(temp)
        if (info["kind"] != "video" or (info["width"], info["height"]) != resolution
                or abs((info["duration_s"] or 0) - plan["duration_s"]) > 0.04):
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"shot {plan['idx']} prepared clip has invalid timing or dimensions")
        temp.replace(path)
        materials.append({"url": str(path.relative_to(directory)), "shot_idx": plan["idx"],
                          "duration_s": plan["duration_s"], "sha256": file_hash(path)})
    receipt = {"fingerprint": digest, "materials": materials, "voice_duration_s": seconds,
               "video_clip_duration": math.ceil(max(durations))}
    temp = receipt_path.with_suffix(".tmp")
    temp.write_text(json.dumps(receipt, indent=2) + "\n")
    temp.replace(receipt_path)
    return receipt
