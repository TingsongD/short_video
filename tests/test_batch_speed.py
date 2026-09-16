"""Offline concurrency, recovery, review dependencies and fast caption timing."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.assets.canvas_cli import CanvasError
from modules.batch.canvas import Canvas
from modules.batch.fast_render import ass_time, literal, subtitles
from modules.batch.scheduler import Scheduler
from modules.batch.state import Batch, Pause, ReviewReady, digest, read, write


@pytest.fixture
def batch(tmp_path):
    write(tmp_path / "next-15-video-plan.json", {"videos": [{"video_number": 1, "products": []}]})
    write(tmp_path / "batch-plan/batch-queue.json", {"batch_id": "speed-test",
        "selection_sha256": digest(tmp_path / "next-15-video-plan.json"), "items": [{}, {}],
        "jimeng_batch_credit_ceiling": 2000, "proposed_tts_batch_credit_ceiling": 8000,
        "proposed_tts_credits_per_video": 4000, "repair_allowance_credits_per_video": 200})
    b = Batch(tmp_path)
    b.configure(5, "ffmpeg")
    b.record_balance(2000, "Mock balance")
    return b


def reserved(batch, count=6):
    v = batch.video(1)
    v.update(project_id="p", canvas_stage="created", jobs={f"clip-{i:02}": {
        "stage": "saved", "kind": "video", "quoted_credits": 60, "submit_id": f"s{i}", "node_id": f"n{i}"}
        for i in range(1, count + 1)})
    batch.reserve_video(1, {key: 60 for key in v["jobs"]})
    return v


def test_five_remote_jobs_with_atomic_ceiling_and_no_sixth(batch):
    v = reserved(batch)
    for i in range(1, 6):
        key = f"clip-{i:02}"
        batch.claim_visual(1, key, 60)
        assert read(batch.path)["videos"]["1"]["spent_hold"] == i * 60
        v["jobs"][key]["stage"] = "accepted"
    with pytest.raises(Pause, match="capacity"):
        batch.claim_visual(1, "clip-06", 60)
    assert v["spent_hold"] == 300
    v["jobs"]["clip-03"]["stage"] = "succeeded"
    batch.claim_visual(1, "clip-06", 60)
    assert v["spent_hold"] == 360


def test_ambiguous_job_blocks_new_spend_even_with_free_slots(batch):
    v = reserved(batch)
    batch.claim_visual(1, "clip-01", 60)
    v["jobs"]["clip-01"]["stage"] = "unknown"
    batch.save()
    with pytest.raises(Pause, match="ambiguous"):
        Batch(batch.root).claim_visual(1, "clip-02", 60)
    assert v["spent_hold"] == 60


def test_parallel_slots_do_not_expand_credit_reservation(batch):
    v = reserved(batch)
    v["reservation"] = 100
    batch.claim_visual(1, "clip-01", 60)
    v["jobs"]["clip-01"]["stage"] = "accepted"
    with pytest.raises(Pause, match="reservation exhausted"):
        batch.claim_visual(1, "clip-02", 60)
    with pytest.raises(Pause, match="active video"):
        batch.claim_visual(2, "clip-01", 1)


@pytest.mark.parametrize("error_code", ["transport_timeout", "cli.download_transport_failed"])
def test_free_download_transient_recovers_same_resource_without_resubmit(batch, monkeypatch, error_code):
    v = reserved(batch, 1)
    v["jobs"]["clip-01"].update(stage="succeeded", output_resource_id="existing")
    calls = []
    class CLI:
        def call(self, *args, **kwargs):
            calls.append(args)
            assert args[:3] == ("resource", "download", "existing")
            if len(calls) < 3:
                raise CanvasError(error_code)
            Path(args[args.index("--output") + 1]).write_bytes(b"complete")
    monkeypatch.setattr("modules.batch.canvas.time.sleep", lambda seconds: None)
    monkeypatch.setattr("modules.batch.canvas.verify_media", lambda *a: {"sha256": digest(a[1]), "bytes": 8})
    path = Canvas(batch, 1, None, CLI()).download("clip-01")
    assert path.read_bytes() == b"complete" and len(calls) == 3
    assert v["jobs"]["clip-01"]["downloaded_at"] and v["spent_hold"] == 0


def test_authentication_failure_is_not_retried(batch):
    v = reserved(batch, 1)
    v["jobs"]["clip-01"].update(stage="succeeded", output_resource_id="existing")
    calls = []
    class CLI:
        def call(self, *args, **kwargs):
            calls.append(args)
            raise CanvasError("login_required")
    with pytest.raises(CanvasError):
        Canvas(batch, 1, None, CLI()).download("clip-01")
    assert len(calls) == 1


def fake_scheduler(batch, reviewed=()):
    v = batch.video(1)
    brief = {"products": [{"slot": i} for i in range(1, 7)],
             "takes": [{"id": f"clip-{i:02}", "slot": i, "text": "New exact narration"} for i in range(1, 7)]}
    v["jobs"] = {**{f"look-{i:02}": {"stage": "downloaded", "node_id": f"look{i}"} for i in range(1, 7)},
                 **{f"clip-{i:02}": {"stage": "saved"} for i in range(1, 7)}}
    accepted = set(reviewed)
    calls = []
    class FakeCanvas:
        def poll(self, key):
            calls.append(("poll", key))
            if key == "clip-02":
                v["jobs"][key]["stage"] = "succeeded"
        def download(self, key):
            calls.append(("download", key))
            v["jobs"][key]["stage"] = "downloaded"
        def bind_outfit(self, key, node):
            calls.append(("outfit", key, node))
        def import_file(self, *args):
            return "exact-voice"
        def attach_audio(self, key, voice, words):
            calls.append(("voice", key, voice, words))
        def submit(self, key):
            calls.append(("submit", key))
            v["jobs"][key]["stage"] = "accepted"
    runner = SimpleNamespace(batch=batch, number=1, v=v, folder=batch.directory(1), canvas=FakeCanvas(),
                             reviewed=lambda key: key in accepted)
    return Scheduler(runner, brief), calls, accepted


def test_scheduler_launches_five_ready_clips_before_waiting(batch):
    scheduler, calls, _ = fake_scheduler(batch, [f"look-{i:02}" for i in range(1, 7)])
    assert scheduler.cycle() is False
    assert [c[1] for c in calls if c[0] == "submit"] == [f"clip-{i:02}" for i in range(1, 6)]
    assert len([c for c in calls if c[0] == "voice"]) == 5
    progress = read(scheduler.folder / "progress.json")
    assert len(progress["in_flight"]) == 5


def test_unreviewed_outfit_never_launches_dependent_video(batch):
    scheduler, calls, _ = fake_scheduler(batch)
    with pytest.raises(ReviewReady):
        scheduler.cycle()
    assert not any(c[0] == "submit" for c in calls)


def test_completed_later_job_is_collected_while_first_remains_running(batch):
    scheduler, calls, _ = fake_scheduler(batch, [f"look-{i:02}" for i in range(1, 7)])
    for i in range(1, 6):
        scheduler.v["jobs"][f"clip-{i:02}"]["stage"] = "running"
    with pytest.raises(ReviewReady, match="clip-02"):
        scheduler.cycle()
    assert ("download", "clip-02") in calls
    assert ("submit", "clip-06") in calls
    assert scheduler.v["jobs"]["clip-01"]["stage"] == "running"


def test_failed_review_prevents_additional_spend(batch):
    scheduler, calls, _ = fake_scheduler(batch)
    scheduler.v["reviews"] = {"look-01": {"status": "failed"}}
    with pytest.raises(Pause, match="failed review"):
        scheduler.cycle()
    assert not any(c[0] == "submit" for c in calls)


def test_reference_repair_gets_a_slot_before_unrelated_clips(batch):
    scheduler, calls, _ = fake_scheduler(batch, [f"look-{i:02}" for i in range(2, 7)])
    scheduler.v["selected_jobs"] = {"look-01": "look-01-repair-01"}
    scheduler.v["jobs"]["look-01-repair-01"] = {"stage": "saved", "replacement_for": "look-01"}
    scheduler.cycle()
    admitted = [c[1] for c in calls if c[0] == "submit"]
    assert admitted[0] == "look-01-repair-01"
    assert len(admitted) == 5 and "clip-01" not in admitted


def test_ass_timing_preserves_every_30fps_event_boundary():
    from fractions import Fraction
    for frame in range(5092):
        h, m, s = ass_time(frame).split(":")
        time = int(h)*3600 + int(m)*60 + Fraction(s)
        assert time <= Fraction(frame, 30)
        if frame:
            assert time > Fraction(frame - 1, 30)


def test_ass_literals_and_previous_caption_collision():
    brief = {"takes": [{"slot": 1, "start_frame": 0}], "products": [{"slot": 1, "label": "Checks & denim"}]}
    words = [{"text": "I'd", "start": 2, "end": 2.001}, {"text": "try", "start": 2.001, "end": 2.5}]
    result = subtitles(brief, words)
    assert "I'd try" in result and "Checks & denim" in result and "&#" not in result
    assert result.count(",Caption,,") == 1
    with pytest.raises(Pause, match="control"):
        literal(r"bad {\pos(0,0)}")


def test_review_pack_keeps_speech_discrepancies_and_never_approves():
    from scripts.batch_review_pack import comparison
    a = [{"text": x, "start": i*.3, "end": i*.3+.2} for i, x in enumerate("I like these blue denim pants with white dots today".split())]
    b = copy.deepcopy(a)
    same = comparison(a, b, 4, 4)
    assert same["asr_normalized_equal"] and not same["same_transcript"]
    b[1]["text"] = "love"
    different = comparison(a, b, 4, 4)
    assert not different["asr_normalized_equal"] and different["differences"]


def test_native_24fps_tail_is_trimmed_to_allocated_30fps_frames(tmp_path):
    import shutil
    import subprocess
    from modules.batch.fast_render import render_input
    from modules.batch.local import probe
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Local media tools unavailable")
    class Local:
        def run(self, args, json_output=False, **kwargs):
            import json
            result = subprocess.run(list(map(str, args)), capture_output=True, check=True, timeout=30)
            return json.loads(result.stdout) if json_output else result.stdout.decode()
    local = Local()
    source = tmp_path / "native.mp4"
    local.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=32x48:r=24:d=2",
               "-c:v", "libx264", source])
    result = render_input(local, source, 45, tmp_path / "cache")
    stream = probe(local, result)["streams"][0]
    assert stream["nb_frames"] == "45" and stream["avg_frame_rate"] == "30/1"
    assert float(stream["duration"]) == 1.5
    assert render_input(local, result, 45, tmp_path / "other") == result
    modified = result.stat().st_mtime_ns
    assert render_input(local, source, 45, tmp_path / "cache") == result
    assert result.stat().st_mtime_ns == modified
    with pytest.raises(Pause, match="cannot cover"):
        render_input(local, source, 90, tmp_path / "cache")


def test_scheduler_resumes_accepted_jobs_without_resubmitting(batch):
    scheduler, calls, _ = fake_scheduler(batch, [f"look-{i:02}" for i in range(1, 7)])
    scheduler.cycle()
    batch.save()
    restored = Batch(batch.root).video(1)
    scheduler.v.clear()
    scheduler.v.update(restored)
    calls.clear()
    with pytest.raises(ReviewReady):
        scheduler.cycle()
    assert len([c for c in calls if c[0] == "poll"]) == 5
    assert not any(c[0] == "submit" and c[1] in {f"clip-{i:02}" for i in range(1, 6)} for c in calls)
