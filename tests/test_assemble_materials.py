"""Actual FFmpeg timing/decoding; native MPT JSON boundary mocked offline."""
import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.assemble.materials import allocations, prepare_clips, file_hash
from modules.assemble.mpt_local import configure_local
from modules.assemble.runner import parse_result, run_batch
from modules.assets.intake import probe
from modules.assets.manifest import build_manifest
from modules.assemble.task_builder import build_task

FIXTURES = Path(__file__).parent / "fixtures"


def inputs(tmp_path):
    sl = json.loads((FIXTURES / "contracts/shot_list.sample.json").read_text())
    sl["shots"] = sl["shots"][:4]
    assets = tmp_path / "assets"
    assets.mkdir()
    for shot in sl["shots"]:
        shot["duration_s"] = 3
        shot["asset_type"] = "image" if shot["idx"] == 3 else "video"
        ext = "png" if shot["idx"] == 3 else "mp4"
        shutil.copy(FIXTURES / "media" / f"good_{shot['asset_type']}.{ext}",
                    assets / f"shot-{shot['idx']:02d}.{ext}")
    shutil.copy(FIXTURES / "media/short_voice.mp3", tmp_path / "voice.mp3")
    return sl, build_manifest(sl["video_id"], assets, 4)


def test_proportional_frame_allocations():
    values = allocations([{"duration_s": 1}, {"duration_s": 2}, {"duration_s": 3}], 12.01)
    assert sum(values) == pytest.approx(361 / 30)
    assert values == pytest.approx([2, 4.033333, 6], abs=1 / 30)


def test_render_still_and_videos_in_order_to_voice_and_reuse(tmp_path):
    sl, manifest = inputs(tmp_path)
    manifest["assets"].reverse()
    receipt = prepare_clips(tmp_path, sl, manifest, (180, 320))
    assert [m["shot_idx"] for m in receipt["materials"]] == [0, 1, 2, 3]
    durations = [probe(tmp_path / m["url"])["duration_s"] for m in receipt["materials"]]
    assert sum(durations) == pytest.approx(receipt["voice_duration_s"], abs=0.04)
    assert all(probe(tmp_path / m["url"])["kind"] == "video" for m in receipt["materials"])
    def no_render(*a, **kw):
        pytest.fail("valid prepared clips should be reused")
    assert prepare_clips(tmp_path, sl, manifest, (180, 320), no_render) == receipt
    task = build_task(sl["video_id"], sl, manifest, {}, "test", prepared=receipt)
    assert [m["url"] for m in task["video_materials"]] == [m["url"] for m in receipt["materials"]]
    assert task["video_count"] == 1 and task["video_concat_mode"] == "sequential"


def test_long_narration_and_wrong_coverage_stop_before_render(tmp_path):
    sl, manifest = inputs(tmp_path)
    shutil.copy(FIXTURES / "media/good_voice.mp3", tmp_path / "voice.mp3")
    with pytest.raises(ValueError, match="cannot cover"):
        prepare_clips(tmp_path, sl, manifest)
    assert not (tmp_path / "prepared").exists()
    bad = copy.deepcopy(manifest)
    bad["assets"][1] = bad["assets"][0]
    with pytest.raises(ValueError, match="exactly once"):
        prepare_clips(tmp_path, sl, bad)


def summary(path):
    return {"total": 1, "succeeded": 1, "failed": 0, "tasks": [{"index": 1,
            "status": "succeeded", "result": {"videos": [str(path)]}}]}


def test_retrieve_actual_vendor_final_not_stale_production_file(tmp_path):
    src = tmp_path / "vendor-tasks" / "result.mp4"
    src.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(FIXTURES / "media/good_video.mp4"),
                    "-i", str(FIXTURES / "media/short_voice.mp3"), "-shortest", "-c:v", "copy",
                    "-c:a", "aac", str(src)], check=True, capture_output=True)
    production = tmp_path / "production"
    production.mkdir()
    (production / "final-1.mp4").write_bytes(b"stale")
    batch = production / "batch.json"
    batch.write_text('[{}]')
    def runner(cmd, **kwargs):
        assert "mpt_local.py" in cmd[5]
        return SimpleNamespace(returncode=0, stdout=json.dumps(summary(src)))
    result = run_batch(batch, runner=runner, output_dir=production)
    assert result["source_finals"] == [str(src)]
    assert file_hash(result["finals"][0]) == file_hash(src)
    def failed(*a, **kw):
        return SimpleNamespace(returncode=1, stdout=json.dumps(summary(src)))
    with pytest.raises(RuntimeError, match="MPT failed"):
        run_batch(batch, runner=failed)


@pytest.mark.parametrize("change", ["failure", "empty", "duplicate", "relative"])
def test_invalid_mpt_summary_rejected(change):
    doc = summary(Path("/vendor/tasks/final.mp4"))
    if change == "failure":
        doc["tasks"][0]["status"] = "failed"
    if change == "empty":
        doc["tasks"][0]["result"]["videos"] = []
    if change == "duplicate":
        doc["tasks"] *= 2
    if change == "relative":
        doc["tasks"][0]["result"]["videos"] = ["final.mp4"]
    with pytest.raises(RuntimeError, match="no final accepted"):
        parse_result(json.dumps(doc), 1)


def test_assembly_runtime_cannot_auto_publish():
    config = SimpleNamespace(app={"upload_post_enabled": True, "upload_post_auto_upload": True})
    configure_local(config)
    assert not config.app["upload_post_enabled"]
    assert not config.app["upload_post_auto_upload"]
    assert config.app["subtitle_provider"] == "whisper"
