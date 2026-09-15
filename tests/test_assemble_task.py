"""M8: mpt_task build maps manifest -> MPT fields; batch caps at 100
(test_task_builder, test_batch_schema)."""
import json
from pathlib import Path

import pytest

from modules.assemble.task_builder import build_batch, build_task, write_batch

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SHOT_LIST = json.loads((FIXTURES / "shot_list.sample.json").read_text())
MANIFEST = json.loads((FIXTURES / "asset_manifest.sample.json").read_text()) | {
    "complete": True, "missing_shots": [],
}
CFG = {"video_aspect": "9:16", "resolution": "1080x1920",
       "video_count_variants": 2, "bgm_volume": 0.15,
       "subtitle_mode": "word_by_word"}


def test_task_maps_manifest_to_mpt_fields():
    t = build_task("v-20260914-001", SHOT_LIST, MANIFEST, CFG, "3 phrases")
    assert t["video_source"] == "local"
    assert t["video_aspect"] == "9:16"
    assert t["video_script"] == SHOT_LIST["script_text"]
    assert t["custom_audio_file"] == "voice.mp3"
    assert t["subtitle_display_mode"] == "word_by_word"
    assert t["video_count"] == 1
    assert t["video_concat_mode"] == "sequential"
    assert t["bgm_volume"] == 0.15


def test_materials_are_manifest_relative_paths():
    t = build_task("v-1", SHOT_LIST, MANIFEST, CFG, "s")
    urls = [m["url"] for m in t["video_materials"]]
    assert urls == [f"assets/shot-0{i}.{ext}" for i, ext in
                    enumerate(["mp4", "mp4", "mp4", "png", "mp4"])]


def test_incomplete_manifest_rejected():
    bad = dict(MANIFEST, complete=False, missing_shots=[2])
    with pytest.raises(ValueError, match="missing"):
        build_task("v-1", SHOT_LIST, bad, CFG, "s")


def test_batch_validates_each_task_and_caps():
    t = build_task("v-1", SHOT_LIST, MANIFEST, CFG, "s")
    assert len(build_batch([t, t])) == 2
    with pytest.raises(ValueError, match="100"):
        build_batch([t] * 101)
    with pytest.raises(Exception):
        build_batch([dict(t, video_source="pexels")])


def test_write_batch_roundtrip(tmp_path):
    t = build_task("v-1", SHOT_LIST, MANIFEST, CFG, "s")
    p = write_batch([t], tmp_path / "batch.json")
    assert json.loads(p.read_text()) == [t]
