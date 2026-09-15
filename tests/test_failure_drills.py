"""M12 failure drills + produce-path ordering: every broken external must
fail LOUDLY at the right gate, never silently.

Drills (all offline, fixture media, injected fakes):
- dead LLM            -> produce fails at `script`
- dead TTS            -> produce fails at `voice`
- empty Jimeng Lane B -> produce fails at `assets`
- no finals from MPT  -> produce fails at `assemble`
- bad QC video        -> produce fails at `qc`
- publish unapproved  -> produce fails at `publish`
- killed idea         -> refused before stage 1
- dead YT quota       -> weekly fails at `radar`
Plus one full happy-path produce run to prove ordering end to end.
"""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.orchestrate import approval, pipeline, stages
from modules.orchestrate.ledger import CostLedger

FIXTURES = Path(__file__).parent / "fixtures"
MEDIA = FIXTURES / "media"
SAMPLE_SHOT = json.loads(
    (FIXTURES / "contracts" / "shot_list.sample.json").read_text())

CFG = {
    "assembly": {"video_aspect": "9:16", "resolution": "1080x1920",
                 "video_count_variants": 2, "bgm_volume": 0.15,
                 "subtitle_mode": "word_by_word"},
    "voice": {"min_duration_s": 15, "max_duration_s": 60},
    "publish": {"max_posts_per_day": 2},
    "readback": {"windows_hours": [48, 168, 672]},
    "costs": {"weekly_cap_usd": 25.0},
}

IDEA = {
    "idea_id": "idea-drill-1", "niche": "psychology_facts",
    "topic": "3 phrases manipulators use in arguments",
    "hook_overlay": "If someone says these 3 phrases, walk away.",
    "target_viewer": "18-34", "payoff": "Counter each phrase.",
    "three_bullets": ["a", "b", "c"], "cta": "Follow",
    "status": "pass",
    "virality_score": 8.0, "hook_score": 8.0,
}
FORMAT = {
    "format_id": "fmt-drill", "name": "listicle", "status": "candidate",
    "niche": "psychology_facts", "hook_type": "onscreen",
    "beats": ["a", "b"], "visual_payoff": "text", "cta_pattern": "Follow",
    "source_video_ids": ["v1"], "wins": 0, "losses": 0,
    "consecutive_losses": 0, "created": "2026-09-14T00:00:00Z",
    "last_used": "2026-09-14T00:00:00Z",
}

SCRIPT = SAMPLE_SHOT["script_text"]


def llm_ok():
    def responder(system, user):
        s = system.lower()
        if "visual director" in s:
            return json.dumps([
                {"prompt_jimeng": f"shot {i}", "asset_type": "video",
                 "pexels_fallback_term": f"term {i}"}
                for i in range(len(SCRIPT.split("\n")) + 2)])
        if "shorts metadata" in s:
            return json.dumps({"title": "Drill Title",
                               "caption": "cap. Follow for more",
                               "hashtags": ["x"]})
        if "faceless short-form video scripts" in s:
            return SCRIPT
        raise AssertionError(f"unexpected prompt: {system[:50]}")
    return FakeLLM(responder)


class FakeTTS:
    def __init__(self, fail=False):
        self.fail = fail

    def synthesize(self, text, out_path):
        if self.fail:
            raise RuntimeError("ElevenLabs 401: dead key")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(MEDIA / "good_voice.mp3", out_path)
        return out_path


class FakePexels:
    def __init__(self, drop=True):
        self.drop = drop

    def fetch(self, term, kind, out_path):
        if not self.drop:
            return False
        src = MEDIA / ("good_image.png" if kind == "image"
                       else "good_video.mp4")
        if kind == "video":
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                            "-i", str(src), "-t", "30", "-c", "copy", str(out_path)],
                           capture_output=True, check=True)
        else:
            shutil.copy(src, out_path)
        return True


def render_final(path, bad=False):
    """Render a real mp4 via ffmpeg lavfi. bad=True -> wrong resolution."""
    size = "640x480" if bad else "1080x1920"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc=duration=20:size={size}:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-shortest", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def make_ctx(tmp_path, *, llm=None, tts=None, pexels=None,
             mpt_runner=None, uploader=None, approve=("spend", "publish")):
    grill = tmp_path / "grill"
    grill.mkdir(parents=True)
    (grill / "d.json").write_text(json.dumps({"ideas": [IDEA]}))
    formats = tmp_path / "formats"
    formats.mkdir()
    (formats / "library.json").write_text(
        json.dumps({"version": 1, "formats": [FORMAT]}))
    appr = tmp_path / "approvals"
    for scope in approve:
        approval.grant(scope, appr)
    return {
        "config": CFG,
        "ledger": CostLedger(path=tmp_path / "ledger.json", weekly_cap=25.0),
        "approvals_dir": appr,
        "grill_dir": grill,
        "hooks_path": Path(__file__).parent.parent / "data" / "hooks" / "bank.json",
        "formats_path": formats / "library.json",
        "base_dir": tmp_path / "production",
        "published_dir": tmp_path / "published",
        "video_id": "v-drill-1",
        "asset_provider": "manual", "asset_fallback": "stock", "stop_after": "publish",
        "prepare_clips": fake_prepare_clips,
        "est": {"llm": 0.05, "elevenlabs": 0.20},
        "llm": llm if llm is not None else llm_ok(),
        "tts": tts or FakeTTS(),
        "pexels": pexels if pexels is not None else FakePexels(),
        "mpt_runner": mpt_runner,
        "uploader": uploader or (lambda v, m: {"youtube": "drill-yt-id"}),
    }


def fake_prepare_clips(directory, shot_list, manifest, resolution):
    # Actual FFmpeg timing is covered in test_assemble_materials; these drills
    # isolate stage failures and downstream approvals.
    from modules.assets.canvas import fingerprint
    return {"fingerprint": fingerprint(shot_list), "video_clip_duration": 30,
            "materials": [{"url": f"assets/{a['file']}"} for a in
                          sorted(manifest["assets"], key=lambda a: a["shot_idx"])]}


def run_produce(idea_id, ctx, tmp_path):
    st = stages.produce_stages(idea_id, ctx)
    return pipeline.run_stages("produce", st, log_dir=tmp_path / "runs")


def good_runner(final_dir):
    def runner(cmd, cwd, stdout, stderr, text, timeout):
        render_final(Path(final_dir) / "final-1.mp4")

        class R:
            returncode = 0
            stdout = json.dumps({"total": 1, "succeeded": 1, "failed": 0,
                                 "tasks": [{"index": 1, "status": "succeeded", "result": {
                                     "videos": [str(Path(final_dir) / "final-1.mp4")]}}]})
        return R()
    return runner


# ---------- happy path ----------

def test_produce_full_order_and_artifacts(tmp_path):
    base = tmp_path / "production" / "v-drill-1"
    ctx = make_ctx(tmp_path, mpt_runner=good_runner(base))
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["status"] == "ok", rec["stages"]
    assert [s["name"] for s in rec["stages"]] == stages.STAGE_ORDER_PRODUCE
    assert all("duration_s" in s for s in rec["stages"])
    # contracts produced + schema-valid
    validate(json.loads((base / "shot_list.json").read_text()),
             "shot_list.schema.json")
    validate(json.loads((base / "assets" / "manifest.json").read_text()),
             "asset_manifest.schema.json")
    assert (base / "voice.mp3").exists()
    assert (base / "final-1.mp4").exists()
    pub = tmp_path / "published" / "v-drill-1.json"
    validate(json.loads(pub.read_text()), "publish_record.schema.json")
    # B2: publish record carries the ffprobe-measured length (render is 20s)
    pub_json = json.loads(pub.read_text())
    assert abs(pub_json["video_len_s"] - 20) < 1.5, pub_json["video_len_s"]
    # ledger: llm x2 (script + metadata) + elevenlabs x1
    services = [e["service"] for e in ctx["ledger"].entries]
    assert services.count("llm") == 2 and services.count("elevenlabs") == 1
    assert ctx["ledger"].spent_week() <= 25.0


# ---------- drills ----------

def test_drill_dead_llm_fails_at_script(tmp_path):
    dead = FakeLLM(lambda s, u: (_ for _ in ()).throw(
        RuntimeError("LLM 401: dead key")))
    ctx = make_ctx(tmp_path, llm=dead,
                   mpt_runner=good_runner(tmp_path / "production" / "v-drill-1"))
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["status"] == "failed" and rec["failed_at"] == "script"
    assert "dead key" in rec["stages"][1]["error"]
    assert [s["name"] for s in rec["stages"]] == ["hook", "script"]
    # nothing downstream ran
    assert not (tmp_path / "published").exists() or not list(
        (tmp_path / "published").glob("*.json"))


def test_drill_dead_tts_fails_at_voice(tmp_path):
    ctx = make_ctx(tmp_path, tts=FakeTTS(fail=True),
                   mpt_runner=good_runner(tmp_path / "production" / "v-drill-1"))
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["failed_at"] == "voice"
    assert "dead key" in rec["stages"][3]["error"]
    # failed before the paid call was logged? no — call was attempted
    assert not any(e["service"] == "elevenlabs"
                   for e in ctx["ledger"].entries)


def test_drill_empty_lane_b_fails_at_assets(tmp_path):
    ctx = make_ctx(tmp_path, pexels=FakePexels(drop=False))
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["failed_at"] == "assets"
    assert "assets incomplete" in rec["stages"][2]["error"]


def test_drill_no_finals_fails_at_assemble(tmp_path):
    def silent_runner(cmd, cwd, stdout, stderr, text, timeout):
        class R:
            returncode = 0
        return R()
    ctx = make_ctx(tmp_path, mpt_runner=silent_runner)
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["failed_at"] == "assemble"
    assert "no final" in rec["stages"][4]["error"]


def test_drill_bad_video_fails_at_qc(tmp_path):
    base = tmp_path / "production" / "v-drill-1"

    def bad_runner(cmd, cwd, stdout, stderr, text, timeout):
        render_final(base / "final-1.mp4", bad=True)  # 640x480, wrong res

        class R:
            returncode = 0
            stdout = json.dumps({"total": 1, "succeeded": 1, "failed": 0,
                                 "tasks": [{"index": 1, "status": "succeeded", "result": {
                                     "videos": [str(base / "final-1.mp4")]}}]})
        return R()
    ctx = make_ctx(tmp_path, mpt_runner=bad_runner)
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["failed_at"] == "qc"
    assert "QC failed" in rec["stages"][5]["error"]


def test_drill_publish_unapproved_blocks(tmp_path):
    base = tmp_path / "production" / "v-drill-1"
    ctx = make_ctx(tmp_path, mpt_runner=good_runner(base),
                   approve=("spend",))  # no publish token
    rec = run_produce("idea-drill-1", ctx, tmp_path)
    assert rec["failed_at"] == "publish"
    assert "not approved" in rec["stages"][6]["error"]
    assert not (tmp_path / "published" / "v-drill-1.json").exists()


def test_drill_killed_idea_refused_before_stages(tmp_path):
    ctx = make_ctx(tmp_path)
    grill = tmp_path / "grill" / "d.json"
    grill.write_text(json.dumps({"ideas": [dict(IDEA, status="kill")]}))
    with pytest.raises(ValueError, match="kill"):
        stages.produce_stages("idea-drill-1", ctx)


def test_drill_dead_yt_quota_fails_weekly_at_radar(tmp_path):
    ctx = {
        "config": CFG,
        "ledger": CostLedger(path=tmp_path / "l.json", weekly_cap=25.0),
        "approvals_dir": tmp_path / "appr",
        "formats_path": tmp_path / "f.json",
        "weekly_dir": tmp_path / "weekly",
        "est": {"llm": 0.05},
        "radar_scan": lambda: (_ for _ in ()).throw(
            RuntimeError("YouTube quota exceeded")),
        "grill_run": lambda r: None,
    }
    approval.grant("spend", ctx["approvals_dir"])
    rec = pipeline.run_stages("weekly", stages.weekly_stages(ctx),
                              log_dir=tmp_path / "runs")
    assert rec["failed_at"] == "radar"
    assert "quota" in rec["stages"][0]["error"]
    assert len(rec["stages"]) == 1
