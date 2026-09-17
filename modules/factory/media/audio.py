"""Audio characteristics (F12 checklist 1): presence, levels, speech
hint. A missing stream is a fact (`present: false`), never silence-as-
zero; loudness alone does not prove speech — `speech` stays "unknown"
unless a transcript exists to confirm it."""
import re
import subprocess

from ..domain.errors import ContractError
from .probe import probe

TIMEOUT = 60
_VOL_RE = re.compile(r"(mean|max)_volume: (-?[0-9.]+) dB")


def audio_characteristics(path):
    info = probe(path)
    if info.audio is None:
        return {"present": False, "mean_db": None, "max_db": None,
                "speech": "unknown", "speech_evidence": "no_audio_stream"}
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(path),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ContractError("audio_measure_failed", "path", str(e))
    vols = {m.group(1): float(m.group(2))
            for m in _VOL_RE.finditer(out.stderr)}
    return {"present": True,
            "mean_db": vols.get("mean"), "max_db": vols.get("max"),
            "sample_rate": info.audio.sample_rate,
            "channels": info.audio.channels,
            # level ≠ speech — stays unknown until a transcript/verifier
            "speech": "unknown", "speech_evidence": "level_only"}
