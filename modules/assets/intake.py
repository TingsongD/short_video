"""M6 intake (Lane B): validate dropped files with ffprobe, map to shot_idx
via filename convention `shot-NN[.jimeng|.stock].<ext>`.

Rules (G6): video duration >= 3s, min dimension >= 720px, mp4/png family.
Corrupt/zero-byte/unparseable files are rejected with a reason.
"""
import json
import re
import subprocess
from pathlib import Path

NAME_RE = re.compile(r"^shot-(\d{2,})(?:\.(jimeng|stock))?\.(mp4|mov|webm|png|jpe?g|webp)$")
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
MIN_DIM = 720
MIN_VIDEO_S = 3.0


def probe(path):
    """ffprobe -> {width, height, duration_s} or raise RuntimeError."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError("missing or zero-byte file")
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "json", str(p),
            ],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError("ffprobe not installed")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe failed")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("no video/image stream found")
    st = streams[0]
    dur = data.get("format", {}).get("duration")
    return {
        "width": int(st.get("width") or 0),
        "height": int(st.get("height") or 0),
        "duration_s": float(dur) if dur else None,
    }


def validate_file(path, kind):
    """Return (ok, info_or_error). kind: 'video'|'image'."""
    try:
        info = probe(path)
    except RuntimeError as e:
        return False, str(e)
    if min(info["width"], info["height"]) < MIN_DIM:
        return False, f"below {MIN_DIM}px min dimension ({info['width']}x{info['height']})"
    if kind == "video":
        if info["duration_s"] is None or info["duration_s"] < MIN_VIDEO_S:
            return False, f"duration {info['duration_s']} < {MIN_VIDEO_S}s"
    return True, info


def scan_folder(assets_dir):
    """Map dropped files -> {shot_idx: {file, kind, source, ok, detail}}.
    Later files for the same shot only override earlier OK ones if valid."""
    found = {}
    for f in sorted(Path(assets_dir).iterdir()):
        m = NAME_RE.match(f.name)
        if not m:
            continue
        idx, source, ext = int(m.group(1)), m.group(2) or "manual", m.group(3).lower()
        kind = "image" if ext in IMAGE_EXTS else "video"
        ok, detail = validate_file(f, kind)
        entry = {
            "file": f.name, "kind": kind, "source": source,
            "ok": ok, "detail": detail,
        }
        if idx not in found or (ok and not found[idx]["ok"]):
            found[idx] = entry
    return found
