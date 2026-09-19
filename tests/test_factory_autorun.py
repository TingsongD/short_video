"""Automatic seed→A–D pipeline (autorun): real application services,
real ffmpeg pipeline, fake remote transports only — no paid calls."""
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_factory_application import application, DiskDrive  # noqa: F401
from modules.factory.analysis.vertex import VertexAnalyzer
from modules.factory.domain.errors import ContractError
from modules.factory.providers.catalog import (CapabilityCatalog,
                                               CapabilitySnapshot,
                                               snapshot_id)
from modules.factory.providers.vertex_auth import VertexAuth
from modules.factory.testing.durable import DiskGeneration
from modules.factory.testing.fakes import (FakeAligner, FakeMusicGen,
                                           FakeTTS)
from modules.factory.testing.fixtures import _moving_mp4, _color_mp4, _png
from modules.factory.autorun.review import build_sections

EXPIRY = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

ANALYZE = {"beats": [
    {"id": "b0", "role": "hook", "start_s": 0, "end_s": 3,
     "visual_event": "dog grabs the ball", "confidence": "uncertain"},
    {"id": "b1", "role": "body", "start_s": 3, "end_s": 6,
     "visual_event": "dog runs across the yard",
     "confidence": "uncertain"},
    {"id": "b2", "role": "cta", "start_s": 6, "end_s": 9,
     "visual_event": "dog drops the ball at the camera",
     "confidence": "uncertain"}],
    "transcript": [
        {"id": "t0", "start_s": 0, "end_s": 3, "text": "watch this dog"},
        {"id": "t1", "start_s": 3, "end_s": 6,
         "text": "he runs so fast"},
        {"id": "t2", "start_s": 6, "end_s": 9, "text": "good boy wins"}],
    "music": {"role": "bed"}, "uncertainty": []}

SCRIPT = {"variants": {
    "A": {"b0": "watch this dog now", "b1": "he runs so fast",
          "b2": "good boy wins"},
    "B": {"b0": "you will not believe this dog"},
    "C": {"b1": "he sprints faster than you think"},
    "D": {"b2": "good boy wins watch this dog"}},
    "hypotheses": {"B": "curiosity hook", "C": "clearer body",
                   "D": "loop ending"}}

REVIEW = {"verdict": "pass", "notes": ["content matches script"]}


def test_machine_timeline_covers_verified_media_tail():
    payload = {"beats": [
        {"id": "b1", "role": "body", "start_s": 0.0, "end_s": 14.0,
         "visual_event": "cat listens"},
        {"id": "b2", "role": "payoff", "start_s": 14.0,
         "end_s": 20.0, "visual_event": "cat blinks"}],
        "transcript": []}
    result = build_sections(payload, 20.201, 606)
    assert result["timeline"][0]["start_s"] == 0.0
    assert result["timeline"][-1]["end_s"] == 20.201


def scripted_transport(results):
    def transport(method, url, payload, headers):
        body = json.loads(payload)
        text = "".join(p.get("text", "")
                       for p in body["contents"][0]["parts"])
        if "split test" in text:
            result = results["script"]
        elif "Review this finished" in text:
            result = results["review"]
        else:
            result = results["analyze"]
        return 200, {}, json.dumps({"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps(result)}]}}]}).encode()
    return transport


class TtsShim:
    """Provider-interface TTS fake with the account/price surface the
    effect route requires."""
    account = "fixture-tts"
    model = "eleven_v3"

    def __init__(self, path):
        self.impl = FakeTTS(path)

    def price(self, request):
        amount = self.impl.price(request.get("text", ""))
        return {"kind": "usage_estimate", "unit": "elevenlabs_credits",
                "amount": amount, "reserve_amount": amount,
                "provisional": False, "rate_basis": "fixture tariff",
                "valid_until": EXPIRY}

    def submit(self, request, **kw):
        return self.impl.submit(request)

    def poll(self, oid):
        return self.impl.observe(oid)

    observe = poll

    def download(self, oid, destination=None):
        return self.impl.download(oid, destination)

    def reconcile(self, operation_id=None, request_hash=None):
        return self.impl.reconcile(operation_id, request_hash)


class MusicShim:
    account = "fixture-music"
    model = "music_v1"

    def __init__(self, path):
        self.impl = FakeMusicGen(path)
        self._path = path

    def price(self, request):
        amount = max(1, int(request.get("music_length_ms", 0)) // 1000)
        return {"kind": "usage_estimate", "unit": "elevenlabs_credits",
                "amount": amount, "reserve_amount": amount,
                "provisional": False, "rate_basis": "fixture tariff",
                "valid_until": EXPIRY}

    def submit(self, request, **kw):
        return self.impl.submit(request)

    def poll(self, oid):
        return self.impl.observe(oid)

    observe = poll

    def download(self, oid, destination=None):
        """A real music route returns the requested length; the fake's
        fixed 6s bed would fail composition's duration check."""
        op = self.impl.doc["ops"].get(oid)
        if op is None or op["status"] != "SUCCEEDED":
            from modules.factory.testing.fakes import ProviderError
            raise ProviderError("output_not_available", transient=True)
        from modules.factory.testing.fakes import _wav_bytes
        seconds = max(1.0, (op["request"].get("music_length_ms")
                            or 6000) / 1000.0)
        payload = _wav_bytes(seconds, freq=110.0)
        import hashlib
        if destination:
            Path(destination).write_bytes(payload)
        return {"operation_id": oid, "bytes": payload,
                "sha256": hashlib.sha256(payload).hexdigest()}

    def reconcile(self, operation_id=None, request_hash=None):
        return self.impl.reconcile(operation_id, request_hash)


class Hypit9:
    """Local analysis transport: word-timed transcript for a 9s source
    plus boundary and tile evidence."""

    def available(self):
        return True

    def transcribe_available(self):
        return True

    def paths(self):
        return {"profileSource": "test"}

    def boundaries(self, src):
        return {"boundaries": [{"t": 3.0, "score": 0.9},
                               {"t": 6.0, "score": 0.8}]}

    def transcribe(self, src, language, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        passages = []
        for i, text in enumerate(("watch this dog", "he runs so fast",
                                  "good boy wins")):
            passages.append({
                "text": text, "start_seconds": i * 3.0,
                "end_seconds": (i + 1) * 3.0,
                "words": [{"text": w, "start_seconds": i * 3.0 + j,
                           "end_seconds": i * 3.0 + j + 0.8}
                          for j, w in enumerate(text.split())]})
        Path(dest).write_text(json.dumps({
            "format": "hypit.transcript@1", "source": str(src),
            "language": language, "audio_seconds": 9.0,
            "passages": passages}))
        return type("R", (), {"returncode": 0, "stdout": "",
                              "stderr": ""})()

    def tiles(self, src, dest_dir, every, transcript=None, start=None,
              end=None, columns=4, rows=3):
        d = Path(dest_dir)
        d.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            _png(d / f"grid-{i}.png")
        return type("R", (), {"returncode": 0, "stdout": "",
                              "stderr": ""})()


def stack(application, review_result=None):
    """Wire the fake provider world the run needs."""
    s, c, act, w, root = application
    s.providers["jimeng_canvas"] = DiskGeneration(root)
    CapabilityCatalog(s.db).put(CapabilitySnapshot(
        schema_version="capability_snapshot.v1",
        id=snapshot_id("jimeng_canvas", "fixture-fast", "", "text"),
        created_at=datetime.now(timezone.utc).isoformat(),
        provider="jimeng_canvas", model="fixture-fast",
        input_mode="text", support="qualified",
        capabilities=s.providers["jimeng_canvas"].capabilities(
            "fixture-fast"),
        valid_until=EXPIRY))
    s.providers["elevenlabs"] = TtsShim(root / "tts.json")
    s.providers["generated_music"] = MusicShim(root / "music.json")
    auth = VertexAuth(lambda: {
        "kind": "oauth", "access_token": "tok", "project": "fixture",
        "identity": "i", "scopes": ["cloud-platform"]}, "fixture")
    results = {"analyze": ANALYZE, "script": SCRIPT,
               "review": review_result or REVIEW}
    s.providers["audiovisual_analysis"] = VertexAnalyzer(
        root / "analysis", s.artifacts, auth, "fixture", "fixture",
        "fixture-analysis",
        {"estimate_usd_micros": 1, "reserve_usd_micros": 2,
         "evidence": "fixture", "valid_until": EXPIRY},
        transport=scripted_transport(results))
    s.audio_work.alignment.aligner = FakeAligner()
    s.ref_analysis.hypit = Hypit9()
    for bid, unit in (("credits-gen", "jimeng_credits"),
                      ("credits-tts", "elevenlabs_credits"),
                      ("credits-usd", "usd_micros")):
        r = act("post", "/api/budgets",
                {"id": bid, "unit": unit, "scope": "aggregate",
                 "scope_key": "", "ceiling": 500, "reviewer": "fixture",
                 "evidence": "offline budget"})
        assert r.status_code == 201, r.text
    return s, c, act, w, root


def drive(s, w, limit=800):
    """Tick the worker until nothing is claimable; jump the durable
    defer clock forward instead of sleeping."""
    n = 0
    while n < limit:
        out = w.tick()
        if out is None:
            waiting = s.db.conn.execute(
                "SELECT 1 FROM jobs WHERE status='ready' AND "
                "next_attempt_at IS NOT NULL").fetchone()
            if waiting:
                future = s.scheduler.clock() + timedelta(seconds=5)
                s.scheduler.clock = lambda: future
                n += 1
                continue
            break
        n += 1
    return n


def make_seed(act, root, seconds=9):
    src = root / "source.mp4"
    _moving_mp4(src, seconds, size="180x320")
    seed = act("post", "/api/seeds",
               {"url": "https://youtu.be/abcdefghijk"}
               ).json()["seed"]["seed"]["id"]
    r = act("post", "/api/imports", content=src.read_bytes(),
            headers={"x-filename": "source.mp4"})
    art = r.json()["artifact"]["id"]
    act("post", f"/api/seeds/{seed}/media", {"artifact_id": art})
    return seed


def launch(act, seed, **over):
    body = {"seed_id": seed, "voice_id": "voice-fixture",
            "language": "en",
            "budget_ids": ["credits-gen", "credits-tts", "credits-usd"],
            "generate_music": True, "visual_reviews": True}
    body.update(over)
    r = act("post", "/api/autoruns", body)
    assert r.status_code == 201, r.text
    return r.json()["run"]


def autorun(s, run_id):
    return s.autorun.get(run_id)


def test_autorun_seed_to_four_finished_variants(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "succeeded", (
        f"stage {run.stage} pause {run.pause}")
    eid = run.state["experiment_id"]
    results = s.experiment_results(eid)
    assert len(results["variants"]) == 4
    shas = {v["final"]["sha256"] for v in results["variants"]}
    assert len(shas) == 4, "each variant produced its own final"
    # B/C/D differ from A in exactly their declared segment.
    for key, seg_id in (("B", "b0"), ("C", "b1"), ("D", "b2")):
        v = next(x for x in results["variants"]
                 if x["variant_key"] == key)
        changed = v["changes"]["changed_segments"]
        assert [x["segment"] for x in changed] == [seg_id], changed
        assert set(changed[0]["fields"]) == {"copy", "picture"}, changed
        assert v["changes"]["summary"], "hypothesis recorded"
        assert v["changes"]["metric"] == v["primary_metric"]
    # Narration + captions are attached, never the seed's audio.
    for v in results["variants"]:
        for seg in v["segments"]:
            if seg.get("copy"):
                assert seg["speech"].get("artifact_id"), seg["id"]
                assert seg["captions"], f"no captions on {seg['id']}"
    # Automated reviews are recorded, labelled, never human.
    reviews = s.collection("reviews")
    kinds = {(r["check_type"], r["reviewer"]) for r in reviews}
    assert ("asset", "auto-pipeline") in kinds
    assert any(r["check_type"] == "automated_visual"
               for r in reviews), "final QC verdicts recorded"
    # No silent publishing or delivery.
    assert not s.collection("publications")
    assert not s.collection("deliveries")
    # Paid calls happened once each — the dedupe surface is real.
    tts_ops = json.loads((root / "tts.json").read_text())["ops"]
    assert len(tts_ops) == 6          # 3 shared + B/C/D changed copies
    gens = list((root / "fake-generation").glob("*.json"))
    assert len(gens) == 6             # 3 shared + 3 changed pictures


def test_autorun_pauses_for_missing_media(application):
    s, c, act, w, root = stack(application)
    seed = act("post", "/api/seeds",
               {"url": "https://youtu.be/abcdefghijk"}
               ).json()["seed"]["seed"]["id"]
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.pause["code"] == "missing_source_media"
    assert run.pause["action"], "resume action required"
    # Attach media, resume — the run completes.
    make_seed_media = root / "late.mp4"
    _moving_mp4(make_seed_media, 9, size="180x320")
    r = act("post", "/api/imports", content=make_seed_media.read_bytes(),
            headers={"x-filename": "late.mp4"})
    act("post", f"/api/seeds/{seed}/media",
        {"artifact_id": r.json()["artifact"]["id"]})
    act("post", f"/api/autoruns/{run.id}/resume", {})
    drive(s, w)
    run = autorun(s, run.id)
    assert run.status == "succeeded", run.pause


def test_autorun_budget_enforcement(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    # A 1-credit experiment budget cannot cover the run's narration;
    # experiment-scoped so it only applies while selected.
    act("post", "/api/budgets",
        {"id": "tiny", "unit": "elevenlabs_credits", "scope": "experiment",
         "scope_key": "run", "ceiling": 1, "reviewer": "fixture",
         "evidence": "offline budget"})
    run = launch(act, seed, budget_ids=["credits-gen", "tiny",
                                        "credits-usd"])
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.pause["code"] == "budget_exhausted", run.pause
    # New authority arrives as a NEW budget the operator selects at
    # resume — ceilings are never edited in place.
    act("post", "/api/budgets",
        {"id": "tts-raised", "unit": "elevenlabs_credits",
         "scope": "experiment", "scope_key": "run", "ceiling": 500,
         "reviewer": "fixture", "evidence": "offline budget raise"})
    act("post", f"/api/autoruns/{run.id}/resume",
        {"budget_ids": ["credits-gen", "tts-raised", "credits-usd"]})
    drive(s, w)
    run = autorun(s, run.id)
    assert run.status == "succeeded", run.pause


def test_autorun_resume_requotes_after_reservation_block(application):
    s, c, act, w, root = stack(application)
    # Aggregate ceilings are enforced even when they are not selected as the
    # funding grant.  This one passes Auto's selected-budget coverage check,
    # then blocks the worker's atomic reservation.
    act("post", "/api/budgets",
        {"id": "global-usd", "unit": "usd_micros", "scope": "aggregate",
         "scope_key": "", "ceiling": 0, "reviewer": "fixture",
         "evidence": "offline global ceiling"})
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.stage == "video_analysis"
    assert run.pause["code"] == "budget_exhausted"
    dead = run.state["analysis_jobs"][0]
    assert s.db.uow().jobs.get(dead)["status"] == "failed"

    # Raising the blocking ceiling and resuming must create a new immutable
    # effect plan instead of looping forever on the terminal paid job.
    act("post", "/api/budgets",
        {"id": "global-usd", "unit": "usd_micros", "scope": "aggregate",
         "scope_key": "", "ceiling": 500, "reviewer": "fixture",
         "evidence": "offline ceiling raise"})
    act("post", f"/api/autoruns/{run.id}/resume", {})
    # Only advance far enough to prove the paid analysis was re-planned; the
    # full end-to-end rendering path is covered by the primary autorun test.
    drive(s, w, limit=12)
    run = autorun(s, run.id)
    assert run.stage != "video_analysis", run.pause
    assert run.state["analysis_jobs"][0] != dead


def test_autorun_resume_has_no_duplicate_charges(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w, limit=40)                 # stop mid-pipeline
    drive(s, w)                           # "restart" and finish
    run = autorun(s, run["id"])
    assert run.status == "succeeded", run.pause
    tts_ops = json.loads((root / "tts.json").read_text())["ops"]
    assert len(tts_ops) == 6
    gens = list((root / "fake-generation").glob("*.json"))
    assert len(gens) == 6
    # effect jobs carry run-derived identities — re-queuing reused them
    jobs = [r[0] for r in s.db.conn.execute(
        "SELECT id FROM jobs WHERE id LIKE 'effect-%'").fetchall()]
    assert len(jobs) == len(set(jobs))


def test_autorun_failed_asset_pauses_with_explanation(application):
    s, c, act, w, root = stack(application)
    # Broken generation: mostly-black output fails the automated check.
    gen = s.providers["jimeng_canvas"]

    def black_download(oid, destination=None):
        row = gen.poll(oid)
        path = gen.remote / (oid + ".mp4")
        if not path.exists():
            _color_mp4(path, row["request"]["duration_s"],
                       size="180x320", color="0x000000")
        payload = path.read_bytes()
        if destination:
            Path(destination).write_bytes(payload)
        import hashlib
        return {"bytes": payload,
                "sha256": hashlib.sha256(payload).hexdigest()}
    gen.download = black_download
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.pause["code"] in ("footage_failed", "asset_review_failed"), \
        run.pause
    assert "review_rejected" in run.pause["detail"] or \
        "footage" in run.pause["detail"].lower()
    # The verdict is recorded as automated evidence — never human.
    rows = [json.loads(r["body"]) for r in s.db.conn.execute(
        "SELECT body FROM records WHERE kind='review' AND "
        "json_extract(body,'$.check_type')='asset'").fetchall()]
    assert rows and all(r["reviewer"] == "auto-pipeline" for r in rows)
    assert any(r["verdict"] == "fail" for r in rows)


def test_autorun_flagged_final_pauses(application):
    s, c, act, w, root = stack(
        application,
        review_result={"verdict": "fail",
                       "notes": ["footage does not match script"]})
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.pause["code"] == "final_qc_flagged"
    assert "script" in run.pause["detail"]


def test_compare_hides_previous_revision_finals(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "succeeded", run.pause
    eid = run.state["experiment_id"]
    first = s.experiment_results(eid)
    assert all("final" in v for v in first["variants"])
    # A new draft revision must never relabel the old finals.
    exp = s._current(eid)
    segments = exp.packaging["segments"]
    variants = []
    for key in "BCD":
        v = s.experiments._variant(eid, key)
        variants.append({
            "key": key, "factor": v.changed_factor,
            "regions": [r.to_dict() if hasattr(r, "to_dict") else r
                        for r in v.allowed_regions],
            "segments": v.segments, "hypothesis": v.hypothesis,
            "primary_metric": v.primary_metric,
            "allowed_fields": ["copy", "speech", "captions", "picture"],
            "dependent_fields": v.dependent_fields})
    s.patch_experiment_draft(eid, {
        "segments": segments, "variants": variants,
        "reason": "copy tweak for a new revision"}, exp.revision)
    after = s.experiment_results(eid)
    assert after["revision"] == exp.revision + 1
    assert all("final" not in v for v in after["variants"]), \
        "stale finals leaked into the new revision"


def test_autorun_missing_voice_choice_rejected(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    r = act("post", "/api/autoruns",
            {"seed_id": seed, "budget_ids": ["credits-gen"]})
    assert r.status_code == 400
    assert r.json()["error"] == "voice_required"
