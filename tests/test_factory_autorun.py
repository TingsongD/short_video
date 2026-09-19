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


def test_declared_uncertainty_needs_local_evidence():
    """Transcript overlap is not visual evidence — a provider-declared
    uncertain/unresolved beat keeps its confidence unless local machine
    evidence (a detected scene boundary at its start, or the media head)
    corroborates the interval."""
    import copy as _copy
    from modules.factory.autorun.review import auto_review_beats
    payload = {"beats": [
        {"id": "b0", "role": "hook", "start_s": 0, "end_s": 3,
         "visual_event": "dog grabs ball", "confidence": "uncertain"},
        {"id": "b1", "role": "body", "start_s": 3, "end_s": 6,
         "visual_event": "dog runs", "confidence": "unresolved"},
        {"id": "b2", "role": "body", "start_s": 6, "end_s": 9,
         "visual_event": "dog drops ball", "confidence": "uncertain"}],
        "transcript": [{"id": "t0", "start_s": 0, "end_s": 9,
                        "text": "good dog"}]}
    out = auto_review_beats(_copy.deepcopy(payload))
    confs = {b["id"]: b["confidence"] for b in out["beats"]}
    assert confs == {"b0": "reviewed",      # media head anchors it
                     "b1": "unresolved",    # no local evidence
                     "b2": "uncertain"}
    out = auto_review_beats(
        _copy.deepcopy(payload),
        evidence={"boundaries": [{"t": 3.0}, {"t": 6.0}]})
    confs = {b["id"]: b["confidence"] for b in out["beats"]}
    assert confs == {"b0": "reviewed", "b1": "reviewed",
                     "b2": "reviewed"}


def test_failed_media_scan_never_passes(tmp_path):
    """A scan that did not run cannot yield a passing review."""
    from modules.factory.autorun import review as checks
    mp4 = tmp_path / "v.mp4"
    _moving_mp4(mp4, 3, size="180x320")
    info = {"streams": [{"codec_type": "video", "codec_name": "h264",
                         "width": 180, "height": 320}],
            "duration_s": 3.0}
    verdict, _ = checks.inspect_asset(
        str(mp4), info, {"kind": "video", "min_duration_s": 3})
    assert verdict == "pass", "baseline real scan must pass"

    missing = lambda *a, **k: (_ for _ in ()).throw(
        FileNotFoundError("ffmpeg"))
    orig = checks.subprocess.run
    checks.subprocess.run = missing
    try:
        verdict, notes = checks.inspect_asset(
            str(mp4), info, {"kind": "video", "min_duration_s": 3})
    finally:
        checks.subprocess.run = orig
    assert verdict == "uncertain"
    assert "did not run" in notes[0]

    def timed_out(*a, **k):
        raise checks.subprocess.TimeoutExpired("ffmpeg", 30)
    checks.subprocess.run = timed_out
    try:
        verdict, _ = checks.inspect_asset(
            str(mp4), info, {"kind": "video", "min_duration_s": 3})
    finally:
        checks.subprocess.run = orig
    assert verdict == "uncertain"

    def nonzero(*a, **k):
        return type("P", (), {"returncode": 1, "stderr": "boom"})()
    checks.subprocess.run = nonzero
    try:
        verdict, _ = checks.inspect_asset(
            str(mp4), info, {"kind": "video", "min_duration_s": 3})
    finally:
        checks.subprocess.run = orig
    assert verdict == "uncertain"


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


def stack(application, review_result=None, script_result=None,
          analyze_result=None):
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
    results = {"analyze": analyze_result or ANALYZE,
               "script": script_result or SCRIPT,
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


def test_autorun_crash_after_paid_dispatch_reuses_work(application):
    """Losing the run-state write after queue committed must re-land on
    the same plan/authorization/jobs — never mint a second paid scope."""
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    run = launch(act, seed)
    for _ in range(800):
        if w.tick() is None:
            if not s.db.conn.execute(
                    "SELECT 1 FROM jobs WHERE status='ready' AND "
                    "next_attempt_at IS NOT NULL").fetchone():
                break
            future = s.scheduler.clock() + timedelta(seconds=5)
            s.scheduler.clock = lambda: future
        st = autorun(s, run["id"])
        if st.state.get("music_jobs"):
            break
    st = autorun(s, run["id"])
    assert st.state.get("music_jobs"), "music dispatch never committed"
    first_jobs = list(st.state["music_jobs"])
    plan_id = st.state["music_plan"]
    auths = s.db.conn.execute(
        "SELECT COUNT(*) FROM records WHERE kind='authorization' AND "
        "json_extract(body,'$.binding.id')=?", (plan_id,)).fetchone()[0]
    assert auths == 1
    auth_id = st.state["music_auth"]
    # The lost write: run record survives without the dispatch state
    # while plan, authorization and queued jobs remain committed.
    for key in ("music_jobs", "music_plan", "music_auth"):
        st.state.pop(key, None)
    s.autorun._put(st)
    drive(s, w)
    st = autorun(s, run["id"])
    assert st.status == "succeeded", (
        f"stage {st.stage} pause {st.pause}")
    assert st.state["music_jobs"] == first_jobs
    assert s.db.conn.execute(
        "SELECT COUNT(*) FROM records WHERE kind='authorization' AND "
        "json_extract(body,'$.binding.id')=?", (plan_id,)).fetchone()[0] \
        == 1, "a second authorization was minted for the same plan"
    assert st.state["music_auth"] == auth_id
    ops = json.loads((root / "music.json").read_text()).get("ops", {})
    assert len(ops) == 1, "the music provider was charged twice"


class HypitMany(Hypit9):
    """Boundary evidence for a dense beat map: a detected cut at every
    beat start so the machine-review gate has local corroboration."""

    def __init__(self, n, seconds):
        self._n, self._seconds = n, seconds

    def boundaries(self, src):
        return {"boundaries": [
            {"t": i * self._seconds / self._n, "score": 0.8}
            for i in range(1, self._n)]}


def test_autorun_chunks_tts_plans_over_twenty_lines(application):
    """Effect plans cap at 20 operations — a run needing more unique
    narration lines must dispatch multiple persisted batches."""
    n = 21
    # b0–b12 are provider-uncertain and get anchored by the detected cut
    # at each start (evidence caps at 12 boundaries); the provider marks
    # the tail reviewed itself.
    beats = [{"id": f"b{i}",
              "role": "hook" if i == 0 else "cta" if i == n - 1
                      else "body",
              "start_s": i * 9 / n, "end_s": (i + 1) * 9 / n,
              "visual_event": f"beat {i}",
              "confidence": "uncertain" if i <= 12 else "reviewed"}
             for i in range(n)]
    analyze = {"beats": beats,
               "transcript": [{"id": f"t{i}", "start_s": b["start_s"],
                               "end_s": b["end_s"],
                               "text": f"source line {i}"}
                              for i, b in enumerate(beats)],
               "music": {"role": "bed"}, "uncertainty": []}
    script = {"variants": {
        "A": {f"b{i}": f"unique line number {i}" for i in range(n)},
        "B": {"b0": "changed hook copy"},
        "C": {"b10": "changed body copy"},
        "D": {"b20": "changed ending copy"}},
        "hypotheses": {"B": "h", "C": "h", "D": "h"}}
    s, c, act, w, root = stack(application, analyze_result=analyze,
                               script_result=script)
    s.ref_analysis.hypit = HypitMany(n, 9)
    seed = make_seed(act, root)
    run = launch(act, seed)
    for _ in range(800):
        out = w.tick()
        st = autorun(s, run["id"]).state
        if st.get("tts_batch_tags"):
            break
        if out is None:
            if s.db.conn.execute(
                    "SELECT 1 FROM jobs WHERE status='ready' AND "
                    "next_attempt_at IS NOT NULL").fetchone():
                future = s.scheduler.clock() + timedelta(seconds=5)
                s.scheduler.clock = lambda: future
            else:
                break
    st = autorun(s, run["id"]).state
    # 24 unique lines → two immutable plans, each persisted under its own
    # tag so a restart lands on the same paid work.
    assert st["tts_batch_tags"] == ["tts", "tts_1"]
    assert len(st["tts_synth_jobs"]) == n + 3
    assert st["tts_plan"] != st["tts_1_plan"]
    assert st["tts_auth"] and st["tts_1_auth"]
    assert len(st["tts_jobs"]) == 20 and len(st["tts_1_jobs"]) == 4


def test_autorun_repeated_line_binds_every_segment(application):
    """One synthesis is bought per unique line, but every segment that
    speaks it gets its own fitted speech record and attachment."""
    repeated = dict(SCRIPT)
    repeated["variants"] = {k: dict(v) for k, v in SCRIPT["variants"].items()}
    repeated["variants"]["A"] = dict(SCRIPT["variants"]["A"])
    repeated["variants"]["A"]["b2"] = repeated["variants"]["A"]["b0"]
    s, c, act, w, root = stack(application, script_result=repeated)
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "succeeded", run.pause
    results = s.experiment_results(run.state["experiment_id"])
    va = next(v for v in results["variants"] if v["variant_key"] == "A")
    segs = {seg["id"]: seg for seg in va["segments"]}
    assert segs["b0"]["speech"]["artifact_id"]
    assert segs["b2"]["speech"]["artifact_id"]
    assert segs["b0"]["captions"]
    assert segs["b2"]["captions"]
    assert segs["b0"]["speech"]["artifact_id"] == \
        segs["b2"]["speech"]["artifact_id"]
    # Every speaking segment across A–D is a fitted speech record —
    # 12 occurrences in total — while the shared line was synthesized
    # once: 5 paid operations for 5 unique normalized texts.
    assert len(s.db.conn.execute(
        "SELECT id FROM records WHERE kind='speechsegment'"
        ).fetchall()) == 12
    tts_ops = json.loads((root / "tts.json").read_text())["ops"]
    assert len(tts_ops) == 5


def test_autorun_flagged_qc_needs_operator_resolution(application):
    """A flagged final must not re-read the same machine verdict forever:
    a plain resume re-pauses without duplicating reviews, recheck buys one
    fresh look, and accept records the human decision that ends the run."""
    flagged = {"verdict": "uncertain", "notes": ["murky ending frame"]}
    s, c, act, w, root = stack(application, review_result=flagged)
    seed = make_seed(act, root)
    rid = launch(act, seed)["id"]
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "paused" and run.pause["code"] == \
        "final_qc_flagged", (run.status, run.pause)
    n_reviews = len(s.collection("reviews"))

    # Plain resume: identical verdicts, same pause, no duplicate rows.
    r = act("post", f"/api/autoruns/{rid}/resume", {})
    assert r.status_code == 200, r.text
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "paused" and run.pause["code"] == \
        "final_qc_flagged"
    assert len(s.collection("reviews")) == n_reviews

    # Recheck: a fresh paid review once; the same verdict flags again.
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"resolve_qc": "recheck"})
    assert r.status_code == 200, r.text
    drive(s, w)
    run = autorun(s, rid)
    assert run.pause.get("code") == "final_qc_flagged"
    # A second recheck of the same flagged variant is refused — the
    # bounded allowance is exhausted, not silently repeated.
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"resolve_qc": "recheck"})
    assert r.status_code != 200
    run = autorun(s, rid)
    assert run.pause.get("code") == "final_qc_flagged"

    # Human acceptance is durable and ends the run.
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"resolve_qc": "accept", "reviewer": "operator-7"})
    assert r.status_code == 200, r.text
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "succeeded", run.pause
    human = [x for x in s.collection("reviews")
             if x.get("reviewer") == "operator-7"]
    assert len(human) == 4
    assert all(x.get("reviewer_type") == "human" for x in human)


def test_autorun_resume_updates_limits_and_valid_until(application):
    """set_params on resume is the audited way out of a limit pause —
    the run continues under the new authority, with a note."""
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    rid = launch(act, seed,
                 limits={"elevenlabs_credits": 1})["id"]
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "paused", run.stage
    assert run.pause["code"] == "limit_too_low", run.pause
    # An expired authorization renewal is rejected.
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"set_params": {"valid_until": past}})
    assert r.status_code != 200
    run = autorun(s, rid)
    assert run.status == "paused"
    future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"set_params": {"limits": {"elevenlabs_credits": 500},
                            "valid_until": future}})
    assert r.status_code == 200, r.text
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "succeeded", run.pause
    assert run.params["limits"]["elevenlabs_credits"] == 500
    assert run.params["valid_until"] == future
    assert any("operator updated limits" in n for n in run.notes)


def test_autorun_pauses_when_requested_music_unavailable(application):
    """Requested generated music + no provider route = explicit pause;
    the operator may then declare the no-music fallback."""
    s, c, act, w, root = stack(application)
    del s.providers["generated_music"]
    seed = make_seed(act, root)
    rid = launch(act, seed)["id"]
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "paused" and run.stage == "music"
    assert run.pause["code"] == "capability_unavailable"
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"set_params": {"generate_music": False}})
    assert r.status_code == 200, r.text
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "succeeded", run.pause
    assert any("no music bed" in n for n in run.notes)


def test_autorun_pauses_when_visual_qc_route_lost(application):
    """Requested visual QC with a missing provider pauses; the operator
    may explicitly finish on technical checks only."""
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    rid = launch(act, seed)["id"]
    # The same route serves upstream analysis; lose it mid-run.
    provider = s.providers["audiovisual_analysis"]
    for _ in range(400):
        out = w.tick()
        run = autorun(s, rid)
        if run.stage in ("compose", "final_qc") or \
                run.status != "running":
            break
        if out is None:
            if s.db.conn.execute(
                    "SELECT 1 FROM jobs WHERE status='ready' AND "
                    "next_attempt_at IS NOT NULL").fetchone():
                future = s.scheduler.clock() + timedelta(seconds=5)
                s.scheduler.clock = lambda: future
            else:
                break
    del s.providers["audiovisual_analysis"]
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "paused" and run.stage == "final_qc"
    assert run.pause["code"] == "capability_unavailable"
    r = act("post", f"/api/autoruns/{rid}/resume",
            {"set_params": {"visual_reviews": False}})
    assert r.status_code == 200, r.text
    drive(s, w)
    run = autorun(s, rid)
    assert run.status == "succeeded", run.pause
    assert any("technical checks only" in n for n in run.notes)


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
    seed = make_seed(act, root)
    run = launch(act, seed)
    # Let the analysis plan be quoted and dispatched, then have an
    # unrelated aggregate ceiling appear before the worker reserves —
    # the race the pre-dispatch check cannot see.
    for _ in range(80):
        drive(s, w, limit=1)
        run = autorun(s, run["id"] if isinstance(run, dict) else run.id)
        jobs = run.state.get("analysis_jobs") or []
        if jobs and s.db.uow().jobs.get(jobs[0])["status"] in (
                "ready", "waiting_dependencies"):
            break
    else:
        raise AssertionError("analysis effect never reached ready")
    assert run.stage == "video_analysis"
    act("post", "/api/budgets",
        {"id": "global-usd", "unit": "usd_micros", "scope": "aggregate",
         "scope_key": "", "ceiling": 0, "reviewer": "fixture",
         "evidence": "offline global ceiling"})
    drive(s, w)
    run = autorun(s, run.id)
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


def test_cover_precheck_names_blocking_aggregate_ceiling(application):
    """A second aggregate ceiling is held in full alongside the first, so
    the pre-dispatch check must report the *minimum* headroom and name
    the ceiling that blocks — not a sum across selected budgets."""
    s, c, act, w, root = stack(application)
    act("post", "/api/budgets",
        {"id": "credits-tts-2", "unit": "elevenlabs_credits",
         "scope": "aggregate", "scope_key": "", "ceiling": 3,
         "reviewer": "fixture", "evidence": "offline second ceiling"})
    seed = make_seed(act, root)
    # Selecting BOTH tts ceilings must not read as 500+3 of headroom.
    run = launch(act, seed, budget_ids=["credits-gen", "credits-tts",
                                        "credits-tts-2", "credits-usd"])
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.pause["code"] == "budget_exhausted", run.pause
    assert "credits-tts-2" in run.pause["detail"]
    assert "every applicable ceiling" in run.pause["detail"]
    # Nothing was dispatched to the paid TTS route.
    assert not (root / "tts.json").exists() or \
        not json.loads((root / "tts.json").read_text()).get("ops")


def test_operator_settle_and_release_holds(application):
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    assert autorun(s, run["id"]).status == "succeeded"
    holds = [r for r in s.collection("reservations")
             if r["status"] == "held" and r["attempt_status"]]
    assert holds, "fake providers report no usage — holds stay held"
    charged = next(r for r in holds if r["attempt_status"] in
                   ("downloaded", "succeeded"))
    # A charged attempt can never be released, only settled on evidence.
    r = act("post", f"/api/reservations/{charged['id']}/release",
            {"reviewer": "fixture", "evidence": "provider failure page"})
    assert r.status_code == 400 and "release_refused" in r.text
    r = act("post", f"/api/reservations/{charged['id']}/settle",
            {"reviewer": "fixture", "evidence": ""})
    assert r.status_code == 400 and "evidence_required" in r.text
    r = act("post", f"/api/reservations/{charged['id']}/settle",
            {"reviewer": "fixture", "kind": "reported_usage",
             "evidence": "x"})
    assert r.status_code == 400 and "bad_settlement_kind" in r.text
    line = next(l for l in charged["lines"]
                if not l["budget_id"].startswith("authority:"))
    from modules.factory.budget import BudgetService
    before = BudgetService(s.db).available(line["budget_id"])
    r = act("post", f"/api/reservations/{charged['id']}/settle",
            {"reviewer": "fixture", "evidence": "invoice line 12",
             "amount": max(line["amount"] - 1, 0)})
    assert r.status_code == 200, r.text
    row = s.db.conn.execute(
        "SELECT status, evidence FROM reservations WHERE id=?",
        (charged["id"],)).fetchone()
    assert row["status"] == "settled"
    assert "invoice_confirmed by fixture" in row["evidence"]
    # Settling below the hold frees exactly the difference.
    after = BudgetService(s.db).available(line["budget_id"])
    assert after == before + (line["amount"] - max(line["amount"] - 1, 0))
    # Idempotent replay with the same amounts is accepted.
    r = act("post", f"/api/reservations/{charged['id']}/settle",
            {"reviewer": "fixture", "evidence": "invoice line 12",
             "amount": max(line["amount"] - 1, 0)})
    assert r.status_code == 200, r.text


def test_generated_copy_bounded_before_and_after_tts(application):
    """Generated copy is filtered by a word budget before any TTS spend;
    copy that passes the budget but fails the MEASURED fit is repaired
    once by reverting that one line to source-derived copy — with no
    repeat charge for unchanged lines and no silent approval."""
    script = json.loads(json.dumps(SCRIPT))
    # 9 words: inside the 3s beat's budget (ceil(7.5*1.1)=9) but the fake
    # voice needs 0.3+9*0.38=3.72s > 3.3s allowed at RATE_MAX.
    script["variants"]["B"]["b0"] = \
        "you will not believe what this dog does next"
    # 12 words: rejected before spend.
    script["variants"]["C"]["b1"] = \
        "he runs so fast that you will not even see him move today"
    s, c, act, w, root = stack(application, script_result=script)
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "succeeded", run.pause
    notes = "\n".join(run.notes)
    assert "variant C beat b1" in notes and "word budget" in notes
    assert "variant B segment b0" in notes and "reverted" in notes
    assert run.state["experiment_revision"] >= 3     # draft, speech, repair
    ops = json.loads((root / "tts.json").read_text())["ops"].values()
    texts = [o["request"]["text"] for o in ops]
    assert len(texts) == len(set(texts)), texts        # no repeat charge
    assert "you will not believe what this dog does next" in texts
    assert "he runs so fast that you will not even see him move today" \
        not in texts
    # A×3 + B long (measured, then repaired) + B fallback + C fallback + D
    assert len(texts) == 7
    assert "he runs fast" in texts                      # C deterministic
    b = s.experiments._variant(run.experiment_id, "B")
    assert next(x["copy"] for x in b.segments if x["id"] == "b0") == \
        "watch this dog"


def test_source_copy_that_cannot_fit_pauses_honestly(application):
    script = json.loads(json.dumps(SCRIPT))
    s, c, act, w, root = stack(application, script_result=script)
    # Make the fake voice much slower so even source-derived copy cannot
    # fit — the run must pause, not shorten words on its own.
    impl = s.providers["elevenlabs"].impl
    orig = impl.submit

    def slow(request):
        out = orig(request)
        impl.doc["ops"][out["operation_id"]]["duration_s"] = 6.0
        impl._save()
        return out
    impl.submit = slow
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert run.status == "paused"
    assert run.pause["code"] == "speech_fit_failed", run.pause
    assert "does not fit" in run.pause["detail"] or \
        "copy_revision_required" in run.pause["detail"]


def test_media_route_404s_on_unknown_artifact(application):
    """GET /api/assets/{id}/media must answer 404, not a 500, when the
    artifact id is unknown — the dashboard probes media URLs eagerly."""
    s, c, act, w, root = application
    r = c.get("/api/assets/art-nonexistent/media")
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_artifact"


def test_local_render_timeout_retries_without_pausing(application):
    """A subprocess timeout in the local, unpaid compose step is a bounded
    retry, not a pause the operator must click through."""
    import subprocess
    s, c, act, w, root = stack(application)
    # The first local render raises the raw subprocess timeout the live
    # run surfaced as handler_error:TimeoutExpired; the second attempt
    # renders normally.
    fast = s.rendering.fast
    real = fast.render
    state = {"tripped": 0}

    def flaky(*a, **k):
        if state["tripped"] == 0:
            state["tripped"] += 1
            raise subprocess.TimeoutExpired(["ffmpeg"], 600)
        return real(*a, **k)
    fast.render = flaky
    seed = make_seed(act, root)
    run = launch(act, seed)
    drive(s, w)
    run = autorun(s, run["id"])
    assert state["tripped"] == 1
    assert run.status == "succeeded", run.pause
    assert not [p for p in run.progress if p.get("code") == "render_failed"]
    retried = s.db.conn.execute(
        "SELECT count(*) FROM events WHERE type='command_retry'").fetchone()[0]
    assert retried == 1


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


def test_final_qc_never_stamps_stale_artifact(application):
    """A final replaced after its review was dispatched earns its own
    verdict — the old machine review is never stamped onto new bytes."""
    s, c, act, w, root = stack(application)
    seed = make_seed(act, root)
    run = launch(act, seed)
    for _ in range(800):
        if w.tick() is None:
            if not s.db.conn.execute(
                    "SELECT 1 FROM jobs WHERE status='ready' AND "
                    "next_attempt_at IS NOT NULL").fetchone():
                break
            future = s.scheduler.clock() + timedelta(seconds=5)
            s.scheduler.clock = lambda: future
        st = autorun(s, run["id"])
        if len(st.state.get("qc_submitted") or {}) == 4:
            break
    st = autorun(s, run["id"])
    assert len(st.state.get("qc_submitted") or {}) == 4
    eid = st.state["experiment_id"]
    old_final = st.state["qc_submitted"]["A"]["artifact_id"]
    swap = root / "swap.mp4"
    _moving_mp4(swap, 9, size="180x320", color="0xcc3366")
    art = s.artifacts.intake_file(swap, provenance="operator_replacement",
                                source_key="swap", requested_kind="video")
    key = f"final:{eid}:a"
    row = s.db.conn.execute("SELECT value FROM meta WHERE key=?",
                            (key,)).fetchone()
    fin = json.loads(row[0])
    fin["artifact_id"], fin["sha256"] = art.id, art.sha256
    with s.db.uow() as u:
        u.conn.execute("INSERT OR REPLACE INTO meta(key,value) "
                       "VALUES(?,?)", (key, json.dumps(fin)))
    drive(s, w)
    st = autorun(s, run["id"])
    assert st.status == "succeeded", st.pause
    assert "A" in (st.state.get("qc_resubmitted") or [])
    reviews = s.collection("reviews")
    stamped = [r for r in reviews if r["check_type"] == "automated_visual"]
    bound = {r["binding"]["artifact_id"] for r in stamped}
    assert art.id in bound, "the replacement final was never reviewed"
    assert old_final not in bound, \
        "a verdict was stamped onto bytes that are no longer the final"


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
