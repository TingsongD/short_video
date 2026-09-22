"""Bounded full-timeline review copies; never replace a delivered final."""
import fcntl
import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

from ..domain.errors import ContractError
from ..media.probe import probe


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _validate(source, derived, maximum):
    if not 0 < derived.byte_count <= maximum:
        raise ContractError("review_proxy_too_large", "artifact_id")
    a, b = source.video, derived.video
    if (not a or not b or (a.width, a.height) != (b.width, b.height)
            or a.avg_frame_rate != b.avg_frame_rate
            or abs(source.duration_s - derived.duration_s) > 0.1
            or bool(source.audio) != bool(derived.audio)
            or (a.nb_frames and b.nb_frames and a.nb_frames != b.nb_frames)):
        raise ContractError("review_proxy_mismatch", "artifact_id",
                            "Review copy must preserve dimensions, frame rate, duration and audio")


def prepare(path, source_sha, root, maximum):
    path, root = Path(path), Path(root)
    if _sha(path) != source_sha:
        raise ContractError("analysis_media_changed", "artifact_id")
    if path.stat().st_size <= maximum:
        return path, {"source_sha256": source_sha, "sha256": source_sha,
                      "derived": False}
    info = probe(path)
    if not math.isfinite(info.duration_s) or info.duration_s <= 0 or not info.video:
        raise ContractError("review_proxy_invalid_source", "artifact_id")
    # Preserve resolution and every frame; bound bitrate instead of dropping
    # scenes, shrinking captions, or truncating the video to meet the limit.
    audio_rate = 128000 if info.audio else 0
    bitrate = int(maximum * 8 * 0.85 / info.duration_s) - audio_rate
    if bitrate < 500000:
        raise ContractError("review_proxy_quality_limit", "artifact_id",
                            "Cannot fit a full-resolution review copy at a usable bitrate")
    folder = root / f"{source_sha}-{maximum}-v1"
    folder.mkdir(parents=True, exist_ok=True)
    output, manifest = folder / "review.mp4", folder / "binding.json"
    with (folder / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if output.is_file() and manifest.is_file():
            try:
                evidence = json.loads(manifest.read_text())
                if (evidence["source_sha256"] == source_sha
                        and evidence["sha256"] == _sha(output)):
                    _validate(info, probe(output), maximum)
                    return output, evidence
            except (KeyError, ValueError):
                pass
        with tempfile.TemporaryDirectory(prefix="encode-", dir=folder) as temp:
            target = Path(temp) / "review.mp4"
            common = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
                      "-map", "0:v:0", "-c:v", "libx264", "-preset", "fast",
                      "-b:v", str(bitrate), "-pix_fmt", "yuv420p",
                      "-passlogfile", str(Path(temp) / "pass")]
            commands = [common + ["-pass", "1", "-an", "-f", "null", "-"],
                        common + ["-pass", "2", "-map", "0:a:0?", "-c:a", "aac",
                                  "-b:a", "128k", "-movflags", "+faststart", str(target)]]
            for command in commands:
                try:
                    result = subprocess.run(command, capture_output=True, timeout=180)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise ContractError("review_proxy_failed", "artifact_id",
                                        type(error).__name__) from None
                if result.returncode:
                    raise ContractError("review_proxy_failed", "artifact_id",
                                        "Local review-copy encoding failed")
            _validate(info, probe(target), maximum)
            if _sha(path) != source_sha:
                raise ContractError("analysis_media_changed", "artifact_id")
            evidence = {"source_sha256": source_sha, "sha256": _sha(target),
                        "derived": True, "byte_count": target.stat().st_size,
                        "duration_s": info.duration_s, "width": info.video.width,
                        "height": info.video.height,
                        "limitation": "Visual review used a bitrate-reduced copy; original technical QC remains required."}
            target.replace(output)
            staged = Path(temp) / "binding.json"
            staged.write_text(json.dumps(evidence, sort_keys=True))
            staged.replace(manifest)
            return output, evidence
