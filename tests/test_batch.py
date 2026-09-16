"""All batch safety checks use fake providers, never network or paid calls."""
import json
from pathlib import Path

import pytest

from modules.assets.canvas_cli import CanvasError
from modules.batch.audio import word_times, compact_intervals, compact_time
from modules.batch.canvas import Canvas
from modules.batch.local import Drive, descendants, same_process
from modules.batch.render import author, cues
from modules.batch.picture import selected_picture, timing_points, interpolate
from modules.batch.runner import Runner, validate_brief
from modules.batch.state import Batch, Pause, digest, exclusive, read, write


@pytest.fixture
def batch(tmp_path):
    write(tmp_path / "next-15-video-plan.json", {"videos": [{"video_number": 1, "theme": "Checks", "products": []}]})
    write(tmp_path / "batch-plan/batch-queue.json", {
        "batch_id": "offline-test", "selection_sha256": digest(tmp_path / "next-15-video-plan.json"),
        "jimeng_batch_credit_ceiling": 1500, "proposed_tts_batch_credit_ceiling": 6000,
        "proposed_tts_credits_per_video": 4000, "repair_allowance_credits_per_video": 200,
        "items": [{"video_number": 1}, {"video_number": 2}], "delivery_folder_id": "folder"})
    b = Batch(tmp_path)
    b.record_balance(1500, "Test account observation")
    return b


def quoted(batch, number=1, amount=100):
    v = batch.video(number)
    v["jobs"] = {"clip-01": {"stage": "saved", "quoted_credits": amount, "node_id": "n", "submit_id": "stable", "kind": "video",
                            "model": "seedance_2.0_fast_vip", "mode": "m2v", "duration": 9, "refs": [], "prompt": "exact words"}}
    batch.reserve_video(number, {"clip-01": amount})
    return v


def test_complete_video_plus_reserve_required_before_any_submission(batch):
    v = batch.video(1)
    v["jobs"] = {"a": {}, "b": {}}
    with pytest.raises(Pause, match="coverage"):
        batch.reserve_video(1, {"a": 10})
    with pytest.raises(Pause, match="COMPLETE"):
        batch.reserve_video(1, {"a": 700, "b": 700})
    assert batch.spent() == 0


def test_topup_does_not_expand_original_cap(batch):
    batch.record_balance(90000, "Later top-up does not authorize more")
    v = batch.video(1)
    v["jobs"] = {"a": {}}
    with pytest.raises(Pause, match="COMPLETE"):
        batch.reserve_video(1, {"a": 1400})


def test_live_balance_drop_reduces_spending(batch):
    batch.record_balance(250, "Another app spent credits")
    with pytest.raises(Pause, match="COMPLETE"):
        quoted(batch)


def test_reservation_persisted_and_double_claim_refused(batch):
    quoted(batch)
    batch.claim_visual(1, "clip-01", 100)
    restarted = Batch(batch.root)
    assert restarted.spent() == 100
    assert restarted.video(1)["jobs"]["clip-01"]["stage"] == "submitting"
    with pytest.raises(Pause, match="already claimed"):
        restarted.claim_visual(1, "clip-01", 100)


def test_single_active_job_and_video(batch):
    v = quoted(batch)
    v["jobs"]["clip-02"] = {"stage": "saved", "quoted_credits": 100}
    batch.reserve_video(1, {"clip-01": 100, "clip-02": 100})
    batch.claim_visual(1, "clip-01", 100)
    with pytest.raises(Pause, match="active Jimeng"):
        batch.claim_visual(1, "clip-02", 100)
    with pytest.raises(Pause, match="active video"):
        quoted(batch, 2)


def test_increased_quote_cannot_be_submitted(batch):
    quoted(batch)
    with pytest.raises(Pause, match="increased"):
        batch.claim_visual(1, "clip-01", 101)
    assert batch.spent() == 0


def test_complete_needs_all_three_gates_and_releases_only_unused_hold(batch):
    v = quoted(batch)
    batch.claim_visual(1, "clip-01", 100)
    v.update(qc={"status": "passed"}, delivery={"state": "verified"}, cleanup={"state": "blocked"})
    with pytest.raises(Pause, match="cleanup"):
        batch.complete(1)
    assert batch.active_number() == 1
    v["cleanup"]["state"] = "verified"
    batch.complete(1)
    assert v["reservation"] == 100 and batch.active_number() == 2 and batch.data["balance"] is None


def test_lock_excludes_second_controller_and_releases_on_exception(tmp_path):
    with exclusive(tmp_path):
        with pytest.raises(Pause, match="lock"):
            with exclusive(tmp_path):
                pass
    with exclusive(tmp_path):
        pass


def test_tts_ceilings_and_ambiguous_response_hold(batch):
    batch.claim_tts(1, "first", "x" * 3990)
    with pytest.raises(Pause, match="ceiling"):
        batch.claim_tts(1, "second", "x" * 11)
    with pytest.raises(Pause, match="already reserved"):
        batch.claim_tts(1, "first", "replacement")


def test_ambiguous_canvas_submission_resumes_saved_id_without_repeat(batch):
    v = quoted(batch)
    v.update(project_id="p", canvas_stage="created")
    class Fake:
        submissions = 0
        waits = []
        def node(self, *args):
            return {"type": "video", "generation": {"model": "seedance_2.0_fast_vip", "mode": "m2v", "ratio": "9:16", "outputCount": 1,
                    "resolution": "720p", "durationSeconds": 9, "references": [], "prompt": "exact words"}}
        def quote(self, *args):
            return {"totalMaxCredits": 100}
        def submit(self, project, node, submit, amount):
            self.submissions += 1
            assert read(batch.path)["videos"]["1"]["spent_hold"] == 100
            raise CanvasError("transport_timeout")
        def call(self, *args, **kwargs):
            self.waits.append(args)
            return {"state": "failed", "operationRef": "stable"}
    fake = Fake()
    canvas = Canvas(batch, 1, None, fake)
    with pytest.raises(CanvasError):
        canvas.finish("clip-01")
    assert v["jobs"]["clip-01"]["stage"] == "unknown"
    with pytest.raises(Pause, match="failed"):
        Canvas(Batch(batch.root), 1, None, fake).finish("clip-01")
    assert fake.submissions == 1 and fake.waits[0][:3] == ("operation", "wait", "stable")


def test_successful_operation_download_failure_keeps_resource_for_retry(batch, monkeypatch):
    monkeypatch.setattr("modules.batch.canvas.time.sleep", lambda seconds: None)
    v = quoted(batch)
    v.update(project_id="p", canvas_stage="created")
    j = v["jobs"]["clip-01"]
    j.update(stage="submitted", authorized_credits=100)
    class Fake:
        waits = 0
        downloads = 0
        def node(self, *args):
            return {"resources": [{"resourceId": "existing", "submitId": "stable", "type": "video"}]}
        def call(self, *args, **kwargs):
            if args[:2] == ("operation", "wait"):
                self.waits += 1
                return {"state": "succeeded", "operationRef": "stable", "resources": [{"state": "succeeded", "resourceId": "existing"}]}
            self.downloads += 1
            raise CanvasError("download_failed")
    fake = Fake()
    for _ in range(2):
        with pytest.raises(CanvasError):
            Canvas(batch, 1, None, fake).finish("clip-01")
    assert fake.waits == 1 and fake.downloads == 6 and j["output_resource_id"] == "existing"


class FakeDriveLocal:
    def __init__(self, path, remote=None, ambiguous=False):
        self.path, self.remote, self.ambiguous = path, remote, ambiguous
        self.uploads = 0
    def run(self, argv, **kwargs):
        if argv[2] == "list":
            return "id\tvideo.mp4" if self.remote else ""
        if argv[2] == "info":
            return "\n".join(f"{k}: {v}" for k, v in self.remote.items())
        self.uploads += 1
        if self.ambiguous:
            raise Pause("lost upload response")
        return "id"


def test_verified_existing_drive_file_avoids_duplicate_upload(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"finished")
    remote = {"Name": path.name, "Mime": "video/mp4", "Size": str(path.stat().st_size), "MD5": digest(path, "md5"), "Parents": "folder"}
    local = FakeDriveLocal(path, remote)
    doc = Drive(local, "folder").upload(path, tmp_path / "receipt.json")
    assert local.uploads == 0 and doc["state"] == "verified"
    remote["MD5"] = "corrupt"
    with pytest.raises(Pause, match="verification failed"):
        Drive(local, "folder").upload(path, tmp_path / "receipt.json")


def test_ambiguous_drive_upload_cannot_repeat(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"final")
    local = FakeDriveLocal(path, ambiguous=True)
    receipt = tmp_path / "receipt.json"
    with pytest.raises(Pause):
        Drive(local, "folder").upload(path, receipt)
    with pytest.raises(Pause, match="ambiguous"):
        Drive(local, "folder").upload(path, receipt)
    assert local.uploads == 1


def test_upload_failure_still_cleans_and_does_not_advance(batch, monkeypatch):
    runner = Runner(batch, 1)
    monkeypatch.setattr(runner, "_run", lambda: (_ for _ in ()).throw(Pause("upload failure")))
    cleaned = []
    monkeypatch.setattr(runner.local, "cleanup", lambda *a: cleaned.append(True) or {"state": "verified"})
    with pytest.raises(Pause, match="upload"):
        runner.run()
    assert cleaned == [True] and batch.active_number() == 1


def test_process_identity_rejects_reused_pid_and_unrelated_tree():
    saved = {"pid": 10, "birth": "today", "command": "worker"}
    assert same_process(saved, dict(saved))
    assert not same_process(saved, {**saved, "birth": "later"})
    assert not same_process(saved, {**saved, "command": "user browser"})
    assert descendants({10: {"ppid": 1}, 11: {"ppid": 10}, 12: {"ppid": 11}, 20: {"ppid": 1}}, {10}) == {10, 11, 12}


def test_caption_alignment_tracks_trim_tempo_and_apostrophe():
    text = "I'd try it."
    a = {"characters": list(text), "character_start_times_seconds": [1 + i*.1 for i in range(len(text))],
         "character_end_times_seconds": [1.1 + i*.1 for i in range(len(text))]}
    words = word_times(a, 1, 1.1, 10, 2)
    assert words[0]["text"] == "I'd" and words[0]["start"] == 10
    assert words[1]["start"] == pytest.approx(10 + .4 / 1.1)


def test_internal_pause_removal_maps_words_to_the_same_audio_edits():
    kept = compact_intervals(5, [(0., .3), (1., 1.7), (3., 3.1), (4.7, 5.)])
    assert kept == pytest.approx([(.245, 1.055), (1.645, 4.755)])
    assert compact_time(1.4, kept) == pytest.approx(.81)
    a = {"characters": list("Hi you"), "character_start_times_seconds": [.3, .4, .5, 1.8, 1.9, 2.],
         "character_end_times_seconds": [.4, .5, .6, 1.9, 2., 2.1]}
    words = word_times(a, 0., 1., 0., 5., kept)
    assert words[1]["start"] == pytest.approx(.965)


def test_authored_caption_does_not_use_broken_numeric_entities(tmp_path):
    write(tmp_path / "audio/words.json", [{"text": "I'd", "start": 2, "end": 2.2}, {"text": "try", "start": 2.3, "end": 2.5}])
    take = {"id": "clip-01", "slot": 1, "start_frame": 0, "end_frame": 300}
    brief = {"takes": [take], "products": [{"slot": 1, "label": "Checks & denim"}]}
    author(tmp_path, brief, {"jobs": {"clip-01": {"file": "assets/clip.mp4"}}}, take)
    text = (tmp_path / "export-clip-01.svml").read_text()
    assert "I&apos;d" in text and "&#x27;" not in text and "Checks &amp; denim" in text
    assert 'end-frame-exclusive="300"' in text and 'src="./assets/clip.mp4"' in text


def test_words_rounded_to_one_frame_display_only_the_complete_caption():
    words = [
        {"text": "Look", "start": 2., "end": 2.19},
        {"text": "at", "start": 2.2, "end": 2.202},
        {"text": "the", "start": 2.204, "end": 2.206},
        {"text": "denim", "start": 2.208, "end": 2.55},
        {"text": "trim.", "start": 2.6, "end": 2.9},
    ]
    captions = cues(words)
    active = [c["text"] for c in captions if c["start"] <= 66 < c["end"]]
    assert active == ["Look at the denim"]
    assert captions[-1]["text"] == "Look at the denim trim."
    assert all(a["end"] <= b["start"] for a, b in zip(captions, captions[1:]))


def test_provisional_quote_references_replaced_without_extra_audio_or_paid_run(batch):
    v = quoted(batch)
    v.update(project_id="p", canvas_stage="created")
    j = v["jobs"]["clip-01"]
    j.update(refs=["avatar", "product", "sample-voice"], prompt="Keep {{node:avatar}} and {{node:product}}",
             quote_outfit_node="avatar", quote_audio_node="sample-voice")
    class Fake:
        edits = []
        def call(self, *args, **kwargs):
            self.edits.append(args)
            assert args[:3] == ("node", "edit", "video")
            return {}
    fake = Fake()
    canvas = Canvas(batch, 1, None, fake)
    canvas.bind_outfit("clip-01", "approved-outfit")
    canvas.attach_audio("clip-01", "exact-performance", "I'd try this.")
    canvas.bind_outfit("clip-01", "approved-outfit")
    canvas.attach_audio("clip-01", "exact-performance", "I'd try this.")
    assert len(fake.edits) == 2 and j["refs"] == ["approved-outfit", "product", "exact-performance"]
    assert "{{node:avatar}}" not in j["prompt"] and j["quoted_credits"] == 100 and batch.spent() == 0


def test_readback_rejects_changed_native_prompt_before_spending(batch):
    v = quoted(batch)
    v.update(project_id="p", canvas_stage="created")
    class Fake:
        def node(self, *args):
            return {"type": "video", "generation": {"model": "seedance_2.0_fast_vip", "mode": "m2v", "ratio": "9:16", "outputCount": 1,
                    "resolution": "720p", "durationSeconds": 9, "references": [], "prompt": "different request"}}
        def submit(self, *args):
            pytest.fail("Changed draft must not be submitted")
    with pytest.raises(Pause, match="prompt changed"):
        Canvas(batch, 1, None, Fake()).finish("clip-01")
    assert batch.spent() == 0


def test_picture_timing_preserves_monotonic_speech_anchors():
    pairs = [{"reference_start": i*.4, "reference_end": i*.4+.2,
              "generated_start": i*.4+.1, "generated_end": i*.4+.3} for i in range(8)]
    points = timing_points(pairs, 4., 4.2)
    assert points[0] == pytest.approx([0., .1])
    for pair in pairs:
        t = (pair["reference_start"] + pair["reference_end"])/2
        assert interpolate(points, t) == pytest.approx(t+.1)
    pairs[3]["generated_start"] = 0.
    pairs[3]["generated_end"] = .02
    with pytest.raises(Pause, match="monotonic"):
        timing_points(pairs, 4., 4.2)


def test_picture_edit_rejects_stale_narration_or_source(tmp_path):
    for name in ("source.mp4", "edit.mp4", "speech.wav"):
        (tmp_path/name).write_bytes(name.encode())
    v = {"jobs": {"clip-01": {"file": "source.mp4"}}, "picture_edits": {"clip-01": {
        "file": "edit.mp4", "sha256": digest(tmp_path/"edit.mp4"), "source_sha256": digest(tmp_path/"source.mp4"),
        "speech_file": "speech.wav", "speech_sha256": digest(tmp_path/"speech.wav")}}}
    assert selected_picture(v, tmp_path, "clip-01") == tmp_path/"edit.mp4"
    (tmp_path/"speech.wav").write_bytes(b"new performance")
    with pytest.raises(Pause, match="stale"):
        selected_picture(v, tmp_path, "clip-01")


def test_render_uses_inspected_local_edit_instead_of_native_picture(tmp_path):
    for name in ("native.mp4", "aligned.mp4", "voice.wav"):
        (tmp_path/name).write_bytes(name.encode())
    write(tmp_path / "audio/words.json", [])
    take = {"id": "clip-01", "slot": 1, "start_frame": 0, "end_frame": 300}
    v = {"jobs": {"clip-01": {"file": "native.mp4"}}, "picture_edits": {"clip-01": {
        "file": "aligned.mp4", "sha256": digest(tmp_path/"aligned.mp4"), "source_sha256": digest(tmp_path/"native.mp4"),
        "speech_file": "voice.wav", "speech_sha256": digest(tmp_path/"voice.wav")}}}
    author(tmp_path, {"takes": [take], "products": [{"slot": 1, "label": "Skort"}]}, v, take)
    markup = (tmp_path/"export-clip-01.svml").read_text()
    assert 'src="./aligned.mp4"' in markup and 'src="./native.mp4"' not in markup


def test_section_join_preserves_frame_clock_despite_rounded_mp4_duration(tmp_path):
    import shutil
    import subprocess
    from modules.batch.render import join_sections
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Local FFmpeg required")

    class Commands:
        def run(self, argv, **kwargs):
            subprocess.run(list(map(str, argv)), check=True, capture_output=True, timeout=30)

    local = Commands()
    paths, takes, cursor = [], [], 0
    for i, frames in enumerate((13, 17)):
        path = tmp_path / f"section-{i}.mp4"
        # Hypit MP4s have silent AAC and millisecond-rounded container durations.
        local.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=96x160:r=30",
                   "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{frames/30:.3f}",
                   "-c:v", "libx264", "-c:a", "aac", path])
        paths.append(path)
        takes.append({"start_frame": cursor, "end_frame": cursor + frames})
        cursor += frames
    sound = tmp_path / "voice.wav"
    local.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=400:duration=1", sound])
    final = tmp_path / "final.mp4"
    join_sections(local, paths, takes, sound, sound, final)
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)]))
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video["avg_frame_rate"] == "30/1"
    assert video["nb_frames"] == "30"
    assert float(video["start_time"]) == 0
    packets = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v",
        "-show_packets", "-show_entries", "packet=pts", "-of", "json", str(final)]))["packets"]
    assert sorted(p["pts"] for p in packets) == [i * 512 for i in range(30)]
