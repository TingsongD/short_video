"""M8 QC on final-*.mp4 via ffprobe/ffmpeg:
- exact resolution (default 1080x1920 from config)
- has an audio stream
- duration within voice_duration +/- tolerance (default 1.5s)
- sane file size (default >= 100 KB)
- subtitle spot check: extract a frame for the operator to eyeball
"""
import json
import math
import subprocess
from pathlib import Path

DEFAULT_RES = (1080, 1920)
MIN_BYTES = 100_000


def probe_full(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError("missing or zero-byte file")
    out = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "stream=codec_type,width,height:format=duration,size",
         "-of", "json", str(p)],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe failed")
    return json.loads(out.stdout)


def qc_video(path, expected_res=DEFAULT_RES, voice_duration=None,
             tolerance_s=1.5, min_bytes=MIN_BYTES):
    """Return (ok, failures[])."""
    failures = []
    try:
        data = probe_full(path)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
        return False, [str(e)]
    streams = data.get("streams") or []
    vids = [s for s in streams if s.get("codec_type") == "video"]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    if not vids:
        return False, ["no video stream"]
    w, h = vids[0].get("width"), vids[0].get("height")
    if (w, h) != expected_res:
        failures.append(f"resolution {w}x{h} != {expected_res[0]}x{expected_res[1]}")
    if not auds:
        failures.append("no audio stream")
    dur = float(data.get("format", {}).get("duration") or 0)
    if not math.isfinite(dur) or dur <= 0:
        failures.append("invalid video duration")
    if voice_duration is not None and abs(dur - voice_duration) > tolerance_s:
        failures.append(
            f"duration {dur:.1f}s drifts >{tolerance_s}s from voice {voice_duration}s"
        )
    size = int(data.get("format", {}).get("size") or 0)
    if size < min_bytes:
        failures.append(f"file too small ({size} bytes)")
    return not failures, failures


def extract_frame(path, at_s=1.0, out_path=None):
    """Pull a frame for manual subtitle spot check."""
    p = Path(path)
    out = Path(out_path or p.with_suffix(f".frame-{at_s:g}s.jpg"))
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", str(at_s), "-i", str(p),
         "-frames:v", "1", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffmpeg frame extract failed")
    return out
