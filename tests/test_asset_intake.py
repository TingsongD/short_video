"""M6: intake validation — good/bad/zero-byte/corrupt + shot mapping
(test_intake)."""
import shutil
from pathlib import Path

from modules.assets.intake import probe, scan_folder, validate_file

FIXTURES = Path(__file__).parent / "fixtures" / "media"


def _stage(tmp_path):
    shutil.copy(FIXTURES / "good_video.mp4", tmp_path / "shot-00.mp4")
    shutil.copy(FIXTURES / "bad_video.mp4", tmp_path / "shot-01.mp4")
    shutil.copy(FIXTURES / "zero_byte.mp4", tmp_path / "shot-02.mp4")
    shutil.copy(FIXTURES / "good_image.png", tmp_path / "shot-03.png")
    shutil.copy(FIXTURES / "good_video.mp4", tmp_path / "shot-04.jimeng.mp4")


def test_valid_mp4_accepted(tmp_path):
    _stage(tmp_path)
    ok, info = validate_file(tmp_path / "shot-00.mp4", "video")
    assert ok and info["width"] == 720 and info["duration_s"] == 3.0


def test_undersized_and_short_video_rejected(tmp_path):
    _stage(tmp_path)
    ok, err = validate_file(tmp_path / "shot-01.mp4", "video")
    assert not ok and "720" in err


def test_zero_byte_rejected(tmp_path):
    _stage(tmp_path)
    ok, err = validate_file(tmp_path / "shot-02.mp4", "video")
    assert not ok and "zero-byte" in err


def test_image_accepted_without_duration():
    ok, info = validate_file(FIXTURES / "good_image.png", "image")
    assert ok and info["width"] == 720


def test_scan_maps_files_to_shot_idx_and_source(tmp_path):
    _stage(tmp_path)
    found = scan_folder(tmp_path)
    assert found[0]["ok"] and found[0]["source"] == "manual"
    assert not found[1]["ok"] and not found[2]["ok"]
    assert found[3]["ok"] and found[3]["kind"] == "image"
    assert found[4]["source"] == "jimeng"


def test_unrelated_filenames_ignored(tmp_path):
    _stage(tmp_path)
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "prompt_cards.md").write_text("# cards")
    found = scan_folder(tmp_path)
    assert set(found) == {0, 1, 2, 3, 4}
