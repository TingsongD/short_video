"""M12 dry E2E (STEP 2): M1 -> M8 on fixtures only — every contract file
appears schema-valid, in pipeline order. Zero network, zero spend.

M1 radar (fake YT transport) -> M2 grill (FakeLLM) -> M3 format extract+match
-> M4 hook select -> M5 shot list -> M6 assets (fixture media) -> M7 voice
(fake TTS transport) -> M8 mpt_task + rendered final QC.
"""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.analytics.verdict import verdict  # noqa: F401  (kept for parity)
from modules.assets.manifest import build_manifest
from modules.assets.queue import render_cards
from modules.assemble.qc import qc_video
from modules.assemble.task_builder import build_task, write_batch, write_task
from modules.common.llm import FakeLLM
from modules.common.schema import validate
from modules.formats import library as format_lib
from modules.formats.extract import draft_format
from modules.formats.match import match_ideas
from modules.grill.gate import run as grill_run
from modules.hooks.select import load_bank, select
from modules.radar.client import YouTubeClient
from modules.radar.quota import QuotaManager
from modules.radar.report import build_report, write_report
from modules.radar.scanner import scan
from modules.script.engine import build_shot_list, save_shot_list
from modules.voice.tts import ElevenLabsTTS, duration_ok

from test_radar_report import NICHES, THRESHOLDS, FakeTransport, NOW

FIXTURES = Path(__file__).parent / "fixtures"
MEDIA = FIXTURES / "media"
CONTRACTS = FIXTURES / "contracts"
SAMPLE_SHOT = json.loads((CONTRACTS / "shot_list.sample.json").read_text())

CFG = {
    "grill": {"pass_hook_score": 7.0, "pass_virality_score": 6.0,
              "ideas_per_cluster": 8},
    "assembly": {"video_aspect": "9:16", "resolution": "1080x1920",
                 "video_count_variants": 2, "bgm_volume": 0.15,
                 "subtitle_mode": "word_by_word"},
}

GENERATE_RESPONSE = json.dumps([{
    "topic": "3 phrases manipulators use in arguments",
    "hook_overlay": "If someone says these 3 phrases, walk away.",
    "target_viewer": "18-34 self-protection viewers",
    "payoff": "Viewer learns the 3 phrases, the bias each exploits, and the counter.",
    "three_bullets": ["Stakes: scripted phrases", "Mechanism: bias each exploits",
                      "Result: one-sentence counter"],
    "cta": "Follow for the next breakdown", "number_claims": [],
}])
JUDGE_RESPONSE = json.dumps({
    "virality_score": 8.0, "hook_score": 8.5, "payoff_confidence": 8.0,
    "three_bullets": ["a", "b", "c"], "judge_notes": "strong",
})
EXTRACT_RESPONSE = json.dumps({
    "name": "Dark-facts 3-item listicle", "hook_type": "onscreen",
    "beats": ["Stakes: vulnerable moment", "Mechanism: 3 items explained",
              "Payoff: counter-move"],
    "visual_payoff": "bold on-screen items", "cta_pattern": "Follow for part 2",
})


def _llm():
    def responder(system, user):
        s = system.lower()
        if "short-form video ideas" in s:
            return GENERATE_RESPONSE
        if "grill judge" in s:
            return JUDGE_RESPONSE
        if "reusable short-form structures" in s:
            return EXTRACT_RESPONSE
        if "visual director" in s:
            return json.dumps([
                {"prompt_jimeng": f"cinematic shot {i}", "asset_type": "video",
                 "pexels_fallback_term": f"fallback {i}"}
                for i in range(7)
            ])
        if "faceless short-form video scripts" in s:
            return SAMPLE_SHOT["script_text"]
        raise AssertionError(f"unexpected LLM system prompt: {system[:60]}")
    return FakeLLM(responder)


def test_e2e_dry_m1_to_m8(tmp_path):
    order = []

    # ---- M1 radar ----
    transport = FakeTransport()
    client = YouTubeClient("fake", QuotaManager(10_000), transport)
    result = scan(client, NICHES, THRESHOLDS, now=NOW)
    report = build_report(result["clusters"], result["scanned_at"],
                          [n["name"] for n in NICHES], client.quota.used)
    validate(report, "niche_report.schema.json")
    rp, _ = write_report(report, tmp_path / "radar", "2026-09-14")
    order.append(rp)

    # ---- M2 grill ----
    doc, audit = grill_run(report, _llm(), CFG["grill"], source_report=str(rp))
    validate(doc, "scored_ideas.schema.json")
    gp = tmp_path / "grill" / "2026-09-14.json"
    gp.parent.mkdir(parents=True)
    gp.write_text(json.dumps(doc, indent=2))
    order.append(gp)
    passing = [i for i in doc["ideas"] if i["status"] == "pass"]
    assert passing, "grill passed nothing — pipeline stalls"

    # ---- M3 format extract + match ----
    cluster = next(n for n in report["niches"] if n["breakout_videos"])
    fmt = draft_format(cluster["breakout_videos"][0], cluster["niche"], _llm())
    lib = {"version": 1, "formats": []}
    fmt_id = format_lib.add(lib, fmt)
    fmt["format_id"] = fmt_id
    format_lib.save(lib, tmp_path / "formats" / "library.json")
    validate(lib, "format_library.schema.json")
    order.append(tmp_path / "formats" / "library.json")
    matches = match_ideas(doc["ideas"], lib["formats"])
    idea = passing[0]
    assert matches[idea["idea_id"]]["format_id"] == fmt_id

    # ---- M4 hook ----
    hooks = load_bank(Path(__file__).parent.parent / "data" / "hooks" / "bank.json")
    hook = select(hooks, idea["niche"], fmt["hook_type"])
    assert hook["text"] and hook["source_url"].startswith("https://")

    # ---- M5 shot list ----
    video_id = "v-e2e-001"
    shot_list = build_shot_list(idea, fmt, hook["text"], video_id, _llm())
    # hook text may differ from the sample script's first line only if LLM
    # echoed it — build_shot_list enforces verbatim hook, so use a FakeLLM
    # whose script starts with the SELECTED hook:
    shot_list = build_shot_list(
        idea, fmt, SAMPLE_SHOT["hook_line"], video_id, _llm())
    validate(shot_list, "shot_list.schema.json")
    sp = save_shot_list(shot_list, out_dir=tmp_path / "production")
    order.append(sp)

    # ---- M6 assets (Lane B drop + manifest) ----
    adir = render_cards(shot_list, base=tmp_path / "production")
    for s in shot_list["shots"]:
        src = MEDIA / ("good_image.png" if s["asset_type"] == "image"
                       else "good_video.mp4")
        shutil.copy(src, adir / f"shot-{s['idx']:02d}{'.png' if s['asset_type'] == 'image' else '.mp4'}")
    manifest = build_manifest(
        video_id, adir, len(shot_list["shots"]),
        {s["idx"]: s["asset_type"] for s in shot_list["shots"]},
    )
    validate(manifest, "asset_manifest.schema.json")
    mp = adir / "manifest.json"
    mp.write_text(json.dumps(manifest, indent=2))
    order.append(mp)
    assert manifest["complete"], f"missing shots {manifest['missing_shots']}"

    # ---- M7 voice ----
    tts = ElevenLabsTTS(
        "fake", "voice-1",
        transport=lambda u, h, p: (MEDIA / "good_voice.mp3").read_bytes(),
    )
    vp = tts.synthesize(shot_list["voice_text"], adir.parent / "voice.mp3")
    assert duration_ok(vp, 15, 60)
    order.append(vp)

    # ---- M8 task build + synthetic final QC ----
    task = build_task(video_id, shot_list, manifest, CFG["assembly"],
                      idea["topic"])
    validate(task, "mpt_task.schema.json")
    tp = write_task(task, video_dir=adir.parent)
    bp = write_batch([task], adir.parent / "batch.json")
    order += [tp, bp]

    final = adir.parent / "final-1.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=20:size=1080x1920:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-shortest", "-pix_fmt", "yuv420p", str(final)],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    ok, failures = qc_video(final, expected_res=(1080, 1920), voice_duration=20)
    assert ok, failures
    order.append(final)

    # ---- order + existence assertions ----
    for p in order:
        assert p.exists(), f"missing contract artifact: {p}"
    mtimes = [p.stat().st_mtime for p in order]
    assert mtimes == sorted(mtimes), "contract files out of pipeline order"
