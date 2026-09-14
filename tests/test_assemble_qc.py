"""M8: QC ffprobe checks (test_qc). Synthetic finals are rendered in-test
with ffmpeg lavfi (offline, ~1s each); fixture media covers failure cases."""
import shutil
import subprocess
from pathlib import Path

import pytest

from modules.assemble.qc import extract_frame, qc_video
from modules.assemble.runner import build_command

FIXTURES = Path(__file__).parent / "fixtures" / "media"


def _render(path, size="1080x1920", dur=20, audio=True):
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc=duration={dur}:size={size}:rate=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    cmd += ["-shortest", "-pix_fmt", "yuv420p", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return path


def test_good_final_passes(tmp_path):
    v = _render(tmp_path / "final-good.mp4")
    ok, failures = qc_video(v, expected_res=(1080, 1920), voice_duration=20)
    assert ok, failures


def test_wrong_resolution_fails(tmp_path):
    v = _render(tmp_path / "final-720.mp4", size="720x1280")
    ok, failures = qc_video(v, expected_res=(1080, 1920), voice_duration=20)
    assert not ok and any("resolution" in f for f in failures)


def test_missing_audio_fails(tmp_path):
    v = _render(tmp_path / "final-noaudio.mp4", dur=5, audio=False)
    ok, failures = qc_video(v, expected_res=(1080, 1920), voice_duration=5)
    assert not ok and "no audio stream" in failures


def test_duration_drift_fails(tmp_path):
    v = _render(tmp_path / "final-short.mp4", dur=10)
    ok, failures = qc_video(v, expected_res=(1080, 1920), voice_duration=20)
    assert not ok and any("drifts" in f for f in failures)


def test_tiny_file_fails(tmp_path):
    v = _render(tmp_path / "final-tiny.mp4", dur=1)
    ok, failures = qc_video(v, expected_res=(1080, 1920), voice_duration=1,
                            min_bytes=10_000_000)
    assert not ok and any("too small" in f for f in failures)


def test_extract_frame_for_subtitle_check(tmp_path):
    v = _render(tmp_path / "final-frame.mp4", dur=5)
    out = extract_frame(v, at_s=1.0)
    assert out.exists() and out.stat().st_size > 0


def test_batch_command_shape():
    cmd = build_command("data/production/v-1/batch.json")
    assert cmd[:3] == ["uv", "run", "python"]
    assert "--batch-file" in cmd and "cli.py" in cmd
