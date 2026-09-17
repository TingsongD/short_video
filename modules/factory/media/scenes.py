"""Scene-change candidates via ffmpeg's scene score (F12 checklist 1).

Local, bounded, read-only on the source. Scores are *candidates* — low
confidence stays visible instead of becoming silent boundaries.
"""
import re
import subprocess

from ..domain.errors import ContractError

_SCENE_RE = re.compile(
    r"pts_time:([0-9.]+).*?scene:([0-9.]+)")
TIMEOUT = 120


def detect_scenes(path, threshold=0.3, limit=200):
    """→ [{"t": seconds, "score": float}] for each frame whose scene
    score exceeds `threshold`. Solid/static sources honestly return []."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(path), "-vf",
             f"select='gt(scene,{threshold})',showinfo",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ContractError("scene_detect_failed", "path", str(e))
    hits = []
    for m in _SCENE_RE.finditer(out.stderr):
        hits.append({"t": float(m.group(1)), "score": float(m.group(2))})
        if len(hits) >= limit:
            break
    return hits
