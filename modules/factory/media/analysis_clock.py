"""Immutable, cached 30 fps inputs for every factory seed analysis route."""
import json
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from ..domain.errors import ContractError
from .probe import probe

POLICY = "analysis-cfr30.v1"


def require_output_30(rate):
    num, den = ((rate.get("num"), rate.get("den")) if isinstance(rate, dict)
                else (getattr(rate, "num", None), getattr(rate, "den", None)))
    if type(num) is not int or type(den) is not int or den <= 0 or num != 30 * den:
        raise ContractError("output_clock_requires_30fps", "output_clock",
                            "Rebuild the blueprint at 30 fps before producing new output")


def is_cfr30(path, info=None):
    info = info or probe(path)
    if not info.video or info.video.avg_frame_rate != 30 or info.video.r_frame_rate != 30:
        return False
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
             "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=120, check=True)
        frames = json.loads(result.stdout)["frames"]
        times = [Fraction(f["best_effort_timestamp_time"]) for f in frames]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise ContractError("analysis_clock_probe_failed", "artifact_id", str(exc)[:200]) from exc
    return bool(times) and all(abs(b-a-Fraction(1, 30)) <= Fraction(1, 100000)
                               for a, b in zip(times, times[1:]))


def analysis_media(artifacts, artifact_id):
    """Return a verified analysis artifact plus its original-byte provenance.

    Normalization is local, has no provider effects, and never replaces the
    registered seed/master or a user-selected proxy. Seconds are not retimed.
    """
    db = artifacts.db
    src = artifacts.verified_path(artifact_id)
    original = db.uow().artifacts.get(artifact_id)
    cache_key = f"{POLICY}:{original['sha256']}"
    cached = db.conn.execute("SELECT value FROM meta WHERE key=?", (cache_key,)).fetchone()
    if cached:
        output_id = cached[0]
        artifacts.verified_path(output_id)
    else:
        info = probe(src)
        if info.kind() != "video":
            raise ContractError("source_not_video", "artifact_id")
        if sum(s.codec_type == "video" for s in info.streams) != 1 or sum(
                s.codec_type == "audio" for s in info.streams) > 1:
            raise ContractError("ambiguous_analysis_streams", "artifact_id",
                                "Attach a seed with one video and at most one audio stream")
        output_id = artifact_id
        if not is_cfr30(src, info):
            with tempfile.TemporaryDirectory(prefix="analysis-30-", dir=artifacts.root / "staging") as tmp:
                dest = Path(tmp) / "analysis.mp4"
                # Keep the canvas, including odd dimensions; no time stretching
                # or independent audio timestamp reset is permitted.
                pixels = "yuv420p" if info.video.width % 2 == info.video.height % 2 == 0 else "yuv444p"
                argv = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src),
                        "-map", "0:v:0", "-map", "0:a:0?", "-vf", "fps=30:start_time=0",
                        "-fps_mode", "cfr", "-r", "30", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18", "-pix_fmt", pixels, "-c:a",
                        "copy" if info.audio and info.audio.codec_name == "aac" else "aac",
                        "-movflags", "+faststart", str(dest)]
                try:
                    result = subprocess.run(argv, capture_output=True, text=True, timeout=900)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise ContractError("analysis_clock_conversion_failed", "artifact_id", str(exc)[:200]) from exc
                if result.returncode:
                    raise ContractError("analysis_clock_conversion_failed", "artifact_id", result.stderr[-500:])
                converted = probe(dest)
                if not is_cfr30(dest, converted) or abs(converted.duration_s-info.duration_s) > 1/30 + .01:
                    raise ContractError("analysis_clock_conversion_invalid", "artifact_id",
                                        "30 fps conversion changed duration or did not produce constant frame timing")
                output_id = artifacts.intake_file(
                    dest, provenance="derived:analysis", source_key=cache_key,
                    source_detail=json.dumps({"policy": POLICY, "source_artifact_id": artifact_id,
                                              "source_sha256": original['sha256']}),
                    requested_kind="video").id
        with db.uow() as u:
            u.conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (cache_key, output_id))
        output_id = db.conn.execute("SELECT value FROM meta WHERE key=?", (cache_key,)).fetchone()[0]
    output = db.uow().artifacts.get(output_id)
    return {"analysis_artifact_id": output_id, "analysis_sha256": output['sha256'],
            "original_artifact_id": artifact_id, "original_sha256": original['sha256'],
            "analysis_clock_policy": POLICY}
