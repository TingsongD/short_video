"""F19 manual scenarios: A's speech build + caption alignment, fit
limits (too long / excess silence), hook-only change isolation, lost
TTS ack + download retry."""
import hashlib
import json

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore
from ..audio import AlignmentService, SpeechService, fit_plan
from ..domain.clocks import FrameInterval, RationalRate
from ..domain.errors import ContractError
from ..execution import Executor
from ..store import Database
from ..testing.fakes import (FakeAligner, FakeTTS, ProviderError)

NOW = "2026-09-17T00:00:00Z"
FPS30 = RationalRate(30, 1)
VOICE = {"voice_id": "v-abc", "model": "eleven_v3", "language": "en",
         "settings": {"stability": 0.5}}

SCRIPT = [("seg-hook", "Stop scrolling — this tank is different.", (0, 120)),
          ("seg-body",
           "Checkerboard knit in a structured fit, a square neckline "
           "that actually holds its shape, ribbed texture you can see "
           "up close, and real pockets deep enough for your phone — "
           "this is the tank that carries the whole outfit, morning "
           "to night, season after season, wash after wash.",
           (120, 660)),
          ("seg-cta",
           "Three colors, sizes extra small through double extra "
           "large — tap the link before it sells out again.",
           (660, 900))]


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db)
    tts = FakeTTS(ctx.run_dir / f"{name}-tts.json")
    ex = Executor(db, provider=tts)
    return db, tts, SpeechService(db, arts, tts=tts, executor=ex), \
        AlignmentService(db, FakeAligner())


def _voice_all(speech, variant, script=SCRIPT):
    outs = {}
    for sid, text, (a, b) in script:
        speech.plan_segment(f"{variant.lower()}-{sid}", variant, text, VOICE,
                            FrameInterval(a, b), now=NOW)
        op = speech.synthesize(f"{variant.lower()}-{sid}", f"job:{variant}-{sid}")
        oid = op["operation"]["operation_id"]
        speech.collect(f"{variant.lower()}-{sid}", oid)
        outs[sid] = speech.collect(f"{variant.lower()}-{sid}", oid)
    return outs


def f19_m01(ctx: CaseContext):
    """Build A's fixture speech; captions align to audio and the final
    timeline matches allocated picture frames."""
    _, _, speech, align = _stack(ctx, "m01")
    _voice_all(speech, "A")
    total_ok, captions = True, []
    for sid, text, (a, b) in SCRIPT:
        seg_id = f"a-{sid}"
        align.align(seg_id, speech.get, now=NOW)
        seg = speech.get(seg_id)
        target_s = (b - a) / 30.0
        fit = fit_plan(seg["duration_s"], target_s)
        total_ok &= fit["fits"]
        cs = align.captions(seg_id, speech.get, fit, FPS30, now=NOW)
        captions += cs.cues
    ctx.check("all_segments_fit", total_ok,
              "every segment fits its allocated frames")
    ctx.check("captions_inside_timeline",
              bool(captions) and all(
                  0 <= c["start_frame"] < c["end_frame"] <= 900
                  for c in captions))
    ctx.check("complete_sentences",
              all(speech.get(f"a-{s}")["text"].strip() and
                  "  " not in speech.get(f"a-{s}")["text"]
                  for s, _, _ in SCRIPT))
    return _result(ctx, "awaiting_manual_review",
                   "all three segments voiced + aligned; captions map "
                   "inside the 900-frame timeline",
                   limitations=["human listens to joins + word "
                                "highlighting"])


def f19_m02(ctx: CaseContext):
    """Too-long hook and excess-silence segment: documented small
    adjustments; excessive fitting blocks for copy revision."""
    _, _, speech, align = _stack(ctx, "m02")
    # too-long hook: 12 words must fit 4 s
    speech.plan_segment("s-long", "A",
                        "This is an extraordinarily long hook that "
                        "simply cannot fit inside four seconds of "
                        "spoken audio no matter what.",
                        VOICE, FrameInterval(0, 120), now=NOW)
    op = speech.synthesize("s-long", "job:s-long")
    speech.collect("s-long", op["operation"]["operation_id"])
    speech.collect("s-long", op["operation"]["operation_id"])
    seg = speech.get("s-long")
    fit = fit_plan(seg["duration_s"], 4.0)
    ctx.check("too_long_blocks",
              fit["fits"] is False
              and fit["reason"] == "speech_too_long"
              and "revise copy" in fit["action"],
              f"needs rate {fit.get('rate_needed')} > {fit.get('rate_limit')}")
    # excess silence: heavy trim requested beyond limit
    try:
        fit_plan(3.0, 4.0, trim_s=1.5)
        ctx.check("trim_limit", False)
    except ContractError as e:
        ctx.check("trim_limit", e.code == "trim_exceeds_limit")
    # small adjustment documented: 4.4 s into 4 s at rate 1.10
    ok = fit_plan(4.4, 4.0)
    ctx.check("small_adjust_documented",
              ok["fits"] and abs(ok["rate"] - 1.1) < 1e-6,
              f"rate={ok['rate']} within limit 1.10")
    return _result(ctx, "passed",
                   "over-limit speech names copy revision, not word "
                   "clipping; trims and rates bounded and documented")


def f19_m03(ctx: CaseContext):
    """Replace B's hook; all other segments identical by hash and
    voice settings."""
    _, _, speech, align = _stack(ctx, "m03")
    _voice_all(speech, "A")
    for sid, _, _ in SCRIPT:               # pipeline marks fitted
        speech._set(f"a-{sid}", status="fitted")
    # variant B reuses A's body/cta via cache; hook differs
    seg_ids = {}
    for sid, text, (a, b) in SCRIPT:
        new_text = "A different hook for B." if sid == "seg-hook" \
            else text
        seg_ids[sid] = f"b-{sid}"
        speech.plan_segment(f"b-{sid}", "B", new_text, VOICE,
                            FrameInterval(a, b), now=NOW)
        speech.reuse_from_cache(f"b-{sid}")
    a_hook = speech.get("a-seg-hook")
    b_hook = speech.get("b-seg-hook")
    ctx.check("hook_changed",
              a_hook["cache_key"] != b_hook["cache_key"])
    for sid in ("seg-body", "seg-cta"):
        a = speech.get(f"a-{sid}")
        b = speech.get(f"b-{sid}")
        ctx.check(f"{sid}_identical",
                  a["cache_key"] == b["cache_key"]
                  and a["audio_sha256"] == b["audio_sha256"]
                  and a["voice"] == b["voice"],
                  "same identity → same waveform reused")
    hits = [speech.cache_lookup(speech.get(f"b-{s}")["cache_key"])
            for s in ("seg-body", "seg-cta")]
    ctx.check("cache_reuse", all(h and h["id"].startswith("a-")
                                 for h in hits),
              "B body/cta reuse A's voiced segments by identity")
    return _result(ctx, "passed",
                   "only the declared hook changed; body+cta segments "
                   "are byte-identical reuses of A's audio")


def f19_m04(ctx: CaseContext):
    """Accept fake TTS but lose the response; restart; separately fail
    the download — unknown reconciles, transfer retries only."""
    db, tts, speech, _ = _stack(ctx, "m04")
    speech.plan_segment("seg-1", "A", "hello world", VOICE,
                        FrameInterval(0, 120), now=NOW)
    req = {"text": "hello world", "voice_id": "v-abc",
           "model": "eleven_v3", "language": "en", "settings": {}}
    rh = hashlib.sha256(json.dumps(req, sort_keys=True).encode()
                        ).hexdigest()
    tts.lose_next_submit()
    ex = Executor(db, provider=tts)
    att = ex.prepare("job:m04", 1, req, kind="tts_synthesis",
                     provider="elevenlabs")
    try:
        ex.submit(att, lambda: tts.submit(req))
        ctx.check("lost_ack_named", False)
    except ProviderError:
        ctx.check("lost_ack_named", True)
    rec = speech.recover("seg-1", request_hash=rh)
    ctx.check("unknown_reconciled",
              rec["status"] in ("voiced", "running", "accepted")
              and len(tts.doc["ops"]) == 1,
              f"{rec['status']}; ops={len(tts.doc['ops'])}")
    # separate: known-success download fails transiently
    if rec["status"] != "voiced":
        rec = speech.recover("seg-1", request_hash=rh)
    oid = list(tts.doc["ops"])[0]
    tts.set_fault("download_fails")
    try:
        speech.collect("seg-1", oid)
        ctx.check("download_fail_named", False)
    except ProviderError as e:
        ctx.check("download_fail_named",
                  e.code == "transport_error")
    tts.clear_fault("download_fails")
    got = speech.collect("seg-1", oid)
    ctx.check("transfer_retry_only",
              got["status"] == "voiced" and len(tts.doc["ops"]) == 1,
              "same op, no second paid synthesis")
    return _result(ctx, "passed",
                   "lost TTS ack reconciled to the same op; failed "
                   "download retried as transfer only")


def implementations():
    return {"F19-M01": f19_m01, "F19-M02": f19_m02,
            "F19-M03": f19_m03, "F19-M04": f19_m04}
