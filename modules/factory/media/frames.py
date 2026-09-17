"""Representative-frame extraction for review proxies (F12 checklist 1).

Each frame lands in the artifact store with provenance linking it to the
source sha and the source timestamp it was taken at — evidence is
traceable, never a floating filename.
"""
import subprocess
from pathlib import Path

from ..domain.errors import ContractError

TIMEOUT = 60


def extract_frame(path, t_seconds, out_path):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{t_seconds:.3f}",
             "-i", str(path), "-frames:v", "1", "-c:v", "png",
             "-f", "image2", str(out)],
            capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ContractError("frame_extract_failed", "path", str(e))
    if r.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise ContractError("frame_extract_failed", "path",
                            r.stderr.decode()[:160])
    return out
