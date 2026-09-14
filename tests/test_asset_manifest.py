"""M6: manifest emission — schema-valid, coverage tracked (test_manifest)."""
import json
import shutil
from pathlib import Path

from modules.assets.manifest import build_manifest, write_manifest
from modules.common.schema import validate

FIXTURES = Path(__file__).parent / "fixtures" / "media"


def _full_dir(tmp_path, n=5):
    d = tmp_path / "assets"
    d.mkdir()
    for i in range(n):
        if i == 3:
            shutil.copy(FIXTURES / "good_image.png", d / "shot-03.png")
        else:
            src = "jimeng" if i == 0 else ("stock" if i == 2 else "manual")
            tag = f".{src}" if src != "manual" else ""
            shutil.copy(FIXTURES / "good_video.mp4", d / f"shot-{i:02d}{tag}.mp4")
    return d


def test_complete_manifest_schema_valid(tmp_path):
    d = _full_dir(tmp_path)
    doc = build_manifest("v-1", d, shot_count=5)
    validate(doc, "asset_manifest.schema.json")
    assert doc["complete"] is True and doc["missing_shots"] == []
    assert [a["shot_idx"] for a in doc["assets"]] == [0, 1, 2, 3, 4]


def test_sources_tracked(tmp_path):
    doc = build_manifest("v-1", _full_dir(tmp_path), shot_count=5)
    by_idx = {a["shot_idx"]: a["source"] for a in doc["assets"]}
    assert by_idx[0] == "jimeng" and by_idx[2] == "stock" and by_idx[1] == "manual"


def test_missing_shot_marks_incomplete(tmp_path):
    d = _full_dir(tmp_path)
    (d / "shot-04.mp4").unlink()
    doc = build_manifest("v-1", d, shot_count=5)
    assert doc["complete"] is False and doc["missing_shots"] == [4]
    validate(doc, "asset_manifest.schema.json")


def test_bad_file_counts_as_missing(tmp_path):
    d = _full_dir(tmp_path)
    (d / "shot-01.mp4").unlink()
    shutil.copy(FIXTURES / "bad_video.mp4", d / "shot-01.mp4")
    doc = build_manifest("v-1", d, shot_count=5)
    assert doc["missing_shots"] == [1]


def test_write_manifest_roundtrip(tmp_path):
    d = _full_dir(tmp_path)
    doc = build_manifest("v-1", d, shot_count=5)
    p = write_manifest(doc, d)
    assert json.loads(p.read_text())["video_id"] == "v-1"
