from modules.factory.testing.authority import approve_operation
"""F19: speech — normalization, identity cache, TTS recovery,
alignment, fit limits, captions, variant reuse."""
import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.audio import (AlignmentService, SpeechService,
                                   apply_fit, fit_plan)
from modules.factory.domain.clocks import FrameInterval, RationalRate
from modules.factory.domain.errors import ContractError
from modules.factory.execution import Executor
from modules.factory.store import Database
from modules.factory.testing.fakes import (FakeAligner, FakeTTS,
                                           ProviderError)

NOW = "2026-09-17T00:00:00Z"
FPS30 = RationalRate(30, 1)
VOICE = {"voice_id": "v-abc", "model": "eleven_v3", "language": "en",
         "settings": {"stability": 0.5}}
IV = FrameInterval(0, 120)          # 4s hook at 30fps


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "arts", db)
    tts = FakeTTS(tmp_path / "tts.json")
    ex = Executor(db, provider=tts)
    speech = SpeechService(db, arts, tts=tts, executor=ex)
    align = AlignmentService(db, FakeAligner())
    return db, arts, tts, ex, speech, align


def _voiced(speech, seg_id="seg-1", text="Stop scrolling, this is it.",
            variant="A", iv=IV):
    speech.plan_segment(seg_id, variant, text, VOICE, iv, now=NOW)
    seg = speech.get(seg_id)
    req = {"text": seg["text"], "voice_id": VOICE["voice_id"], "model": VOICE["model"], "language": "en", "settings": VOICE["settings"]}
    aid = approve_operation(speech.db, speech.executor, req, f"job:{seg_id}")
    out = speech.synthesize(seg_id, f"job:{seg_id}", attempt_id=aid)
    speech.collect(seg_id, out["operation"]["operation_id"])
    speech.collect(seg_id, out["operation"]["operation_id"])
    return out


def test_normalization_strips_markup_and_numbers(stack):
    _, _, _, _, speech, _ = stack
    assert speech.normalize("It's the 1st of 3!") == \
        "It is the first of three!"
    assert speech.normalize("**bold** move") == "bold move"


def test_normalize_rejects_empty(stack):
    _, _, _, _, speech, _ = stack
    with pytest.raises(ContractError, match="empty_speech_text"):
        speech.normalize("***")


def test_segment_identity_includes_voice_and_text(stack):
    _, _, _, _, speech, _ = stack
    k1 = speech.cache_key(VOICE, "hello")
    k2 = speech.cache_key(VOICE, "hello")
    k3 = speech.cache_key(dict(VOICE, voice_id="v-other"), "hello")
    k4 = speech.cache_key(VOICE, "hello!")
    assert k1 == k2 and k1 != k3 and k1 != k4


def test_synthesize_collect_measures(stack):
    _, _, _, _, speech, _ = stack
    _voiced(speech)
    seg = speech.get("seg-1")
    assert seg["status"] == "voiced"
    assert seg["duration_s"] and seg["duration_s"] > 1.0
    assert seg["audio_sha256"]


def test_alignment_words_monotonic(stack):
    _, _, _, _, speech, align = stack
    _voiced(speech)
    al = align.align("seg-1", speech.get, now=NOW)
    assert al.words and al.audio_sha256 == \
        speech.get("seg-1")["audio_sha256"]
    ends = [w["end_s"] for w in al.words]
    assert ends == sorted(ends)


def test_fit_pad_and_rate(stack):
    assert fit_plan(2.0, 4.0)["pad_s"] == 2.0
    f = fit_plan(4.4, 4.0)
    assert f["fits"] and abs(f["rate"] - 1.1) < 1e-6
    too = fit_plan(6.0, 4.0)
    assert too["fits"] is False and too["reason"] == "speech_too_long"
    assert "revise copy" in too["action"]
    # A short punchline on a long visual beat pads; it does not block.
    sparse = fit_plan(2.0, 9.0)
    assert sparse["fits"] is True and sparse["pad_s"] == 7.0
    assert sparse["sparse"] is True


def test_trim_limit(stack):
    with pytest.raises(ContractError, match="trim_exceeds_limit"):
        fit_plan(3.0, 4.0, trim_s=1.5)
    # trim 0.5/edge leaves 2.0s spoken → exactly PAD_MAX fits
    assert fit_plan(3.0, 4.0, trim_s=0.5)["fits"]


def test_never_truncates_words(stack):
    """Oversized speech returns a revision action — not clipped words."""
    too = fit_plan(9.0, 4.0)
    assert too["fits"] is False
    with pytest.raises(ContractError, match="unfitted_speech"):
        apply_fit([{"w": "a", "start_s": 0, "end_s": 1}], too)


def test_captions_map_through_fit(stack):
    _, _, _, _, speech, align = stack
    _voiced(speech)
    align.align("seg-1", speech.get, now=NOW)
    seg = speech.get("seg-1")
    seg = speech.fit("seg-1")
    fit = seg["fit"]
    cs = align.captions("seg-1", speech.get, fit, FPS30,
                        speech_hash=seg["speech_hash"], now=NOW)
    assert cs.cues and cs.cues[0]["start_frame"] >= 0
    assert all(c["end_frame"] <= 120 for c in cs.cues)


def test_cache_reuse_across_variants(stack):
    """Same text+voice in variant B reuses A's voiced segment."""
    _, _, _, _, speech, _ = stack
    _voiced(speech, seg_id="seg-a", variant="A")
    speech.fit("seg-a")
    seg_b = speech.plan_segment("seg-b", "B",
                                "Stop scrolling, this is it.", VOICE,
                                IV, now=NOW)
    hit = speech.cache_lookup(seg_b.cache_key)
    assert hit["id"] == "seg-a"
    reused = speech.reuse_from_cache("seg-b")
    assert reused["id"] == "seg-a"
    b = speech.get("seg-b")
    assert b["audio_sha256"] == hit["raw_audio_sha256"] and \
        b["status"] == "voiced"
    changed = speech.plan_segment("seg-b2", "B", "Different hook.",
                                  VOICE, IV, now=NOW)
    assert speech.cache_lookup(changed.cache_key) is None


def test_lost_ack_recovers_same_op(stack):
    _, _, tts, ex, speech, _ = stack
    speech.plan_segment("seg-1", "A", "hello world", VOICE, IV, now=NOW)
    tts.lose_next_submit()
    req = {"text": "hello world", "voice_id": "v-abc",
           "model": "eleven_v3", "language": "en", "settings": {}}
    import json, hashlib
    rh = hashlib.sha256(json.dumps(req, sort_keys=True).encode()
                        ).hexdigest()
    att = approve_operation(speech.db, ex, req, "job:s")
    with pytest.raises(ProviderError):
        ex.submit(att, lambda: tts.submit(req))
    assert len(tts.doc["ops"]) == 1        # remote accepted anyway
    rec = speech.recover("seg-1", request_hash=rh)
    assert rec["status"] in ("voiced", "running", "accepted")
    assert len(tts.doc["ops"]) == 1        # no duplicate synthesis


def test_download_retry_not_regeneration(stack):
    _, _, tts, _, speech, _ = stack
    out = _voiced(speech)
    oid = out["operation"]["operation_id"]
    tts.set_fault("download_fails")
    with pytest.raises(ProviderError, match="transport_error"):
        speech.collect("seg-1", oid)
    tts.clear_fault("download_fails")
    got = speech.collect("seg-1", oid)
    assert got["status"] == "voiced" and len(tts.doc["ops"]) == 1


def test_approve_pins_speech_hash(stack):
    _, _, _, _, speech, _ = stack
    _voiced(speech)
    with pytest.raises(ContractError, match="not_fitted"):
        speech.approve("seg-1", "h2")     # voiced isn't fitted
    fitted = speech.fit("seg-1")
    out = speech.approve("seg-1", fitted["speech_hash"], reviewer="devin")
    assert out["status"] == "approved" and out["speech_hash"] == fitted["speech_hash"]
    with pytest.raises(ContractError, match="revision_mismatch"):
        speech.approve("seg-1", "different")
