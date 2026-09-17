from modules.factory.testing.authority import approve_operation
"""F20 manual scenarios: exact-duration beds, clip/missing QC, frozen
mix confinement, generation recovery vs imported provenance."""
import hashlib
import json

from .cases_f01 import CaseContext, _result
from ..artifacts.registry import ArtifactStore
from ..audio import MixService, MusicService, pcm
from ..domain.errors import ContractError
from ..execution import Executor
from ..store import Database
from ..testing.fakes import (FakeAudioAnalyzer, FakeMusicGen,
                             ProviderError, _wav_bytes)

NOW = "2026-09-17T00:00:00Z"


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db)
    return db, arts, MusicService(db, arts, analyzer=FakeAudioAnalyzer()), \
        MixService(db, arts)


def _src(arts, seconds=6.0, freq=110.0, key="bed-src"):
    return arts.intake_bytes(_wav_bytes(seconds, freq=freq),
                             provenance="manual", source_key=key,
                             requested_kind="audio")


def f20_m01(ctx: CaseContext):
    """30 s and 169.7 s beds: exact durations, declared joins, measured
    levels for speech/music balance."""
    _, arts, music, mix = _stack(ctx, "m01")
    art = _src(arts)
    music.import_bed("bed-1", art.id, license_ref="lic:fixture",
                     now=NOW)
    b30 = music.construct_bed("bed-1", 30.0)
    music.import_bed("bed-2", art.id, license_ref="lic:fixture",
                     now=NOW)
    b169 = music.construct_bed("bed-2", 169.7)
    ctx.check("exact_30s",
              abs(b30["measured"]["duration_s"] - 30.0) < 0.01)
    ctx.check("exact_169_7s",
              abs(b169["measured"]["duration_s"] - 169.7) < 0.01)
    ctx.check("joins_declared",
              b30["construction"]["joins_inspected"] == 5
              and all("crossfade_in_s" in l
                      for l in b30["construction"]["loops"][1:]),
              f"{b30['construction']['joins_inspected']} joins, "
              f"crossfade {b30['construction']['crossfade_s']}s")
    mix.freeze("mp-1", "exp1", "bed-1",
               {"music_gain_db": -14.0,
                "loudness_target": {"rms_dbfs": -16.0,
                                    "basis": "fixture qualification"}},
               now=NOW)
    speech = pcm.sine(4.0, freq=440.0, amp=10000)
    out = mix.mix("mp-1", [
        {"artifact_id": b30["artifact_id"], "kind": "music",
         "offset_s": 0.0},
        {"samples": speech, "kind": "speech", "offset_s": 1.0}],
        out_s=30.0, artifact_name="m01-mix")
    ctx.check("measured_balance",
              out["measured"]["rms_dbfs"] is not None
              and out["measured"]["peak_dbfs"] is not None)
    return _result(ctx, "awaiting_manual_review",
                   "both beds exact to the sample; 5 declared joins on "
                   "30 s; mix levels measured (rms/peak)",
                   limitations=["human listens at joins/start/end"])


def f20_m02(ctx: CaseContext):
    """Over-loud fixture → named clip with documented gain repair;
    missing audio → explicit error, not silent fallback."""
    _, arts, music, mix = _stack(ctx, "m02")
    hot = _src(arts, seconds=4.0, key="hot-src")
    music.import_bed("bed-hot", hot.id, license_ref="lic", now=NOW)
    mix.freeze("mp-hot", "exp1", "bed-hot", {"music_gain_db": 20.0},
               now=NOW)
    out = mix.mix("mp-hot", [{"artifact_id": hot.id, "kind": "music",
                              "offset_s": 0.0}], out_s=4.0)
    ctx.check("clip_repaired_documented",
              out["clipped"] is False
              and "repaired_db" in out["measured"],
              f"-{out['measured'].get('repaired_db')} dB documented")
    mix.freeze("mp-miss", "exp1", "bed-none", {}, now=NOW)
    try:
        mix.mix("mp-miss", [{"artifact_id": "art:gone",
                             "kind": "music", "offset_s": 0.0}],
                out_s=1.0)
        ctx.check("missing_named", False)
    except ContractError as e:
        ctx.check("missing_named", e.code == "unknown_artifact")
    return _result(ctx, "passed",
                   "over-loud input got a measured gain repair; missing "
                   "audio raised unknown_artifact — no silent fallback")


def f20_m03(ctx: CaseContext):
    """A/B with different hook speech: same music asset/envelope;
    treatment changes confined to the declared region."""
    _, arts, music, mix = _stack(ctx, "m03")
    art = _src(arts)
    music.import_bed("bed-1", art.id, license_ref="lic", now=NOW)
    cfg = {"music_gain_db": -14.0,
           "duck": {"enabled": True, "amount_db": 8.0,
                    "regions": [{"start": 0, "end": 120}]}}
    mix.freeze("mp-a", "exp1", "bed-1", dict(cfg), now=NOW)
    mix.freeze("mp-b", "exp1", "bed-1", dict(cfg), now=NOW)
    # different hook speech changes duck only inside [0,120)
    a = mix.mix("mp-a", [{"artifact_id": art.id, "kind": "music",
                          "offset_s": 0.0},
                         {"samples": pcm.sine(4.0, 440.0),
                          "kind": "speech", "offset_s": 0.0}],
                out_s=30.0)
    b = mix.mix("mp-b", [{"artifact_id": art.id, "kind": "music",
                          "offset_s": 0.0},
                         {"samples": pcm.sine(4.0, 330.0),
                          "kind": "speech", "offset_s": 0.0}],
                out_s=30.0)
    unchanged = [{"start_frame": 120, "end_frame": 900}]
    ctx.check("unchanged_identical",
              mix.assert_unchanged_identical("mp-a", "mp-b", unchanged))
    ctx.check("same_music_master",
              mix.get("mp-a")["music_bed_id"] ==
              mix.get("mp-b")["music_bed_id"] == "bed-1")
    ctx.check("treatment_confined",
              mix.region_parameters("mp-a", {"start_frame": 0,
                                             "end_frame": 120})
              ["duck_db"] == -8.0,
              "duck applies only in declared hook region")
    return _result(ctx, "passed",
                   "identical bed + parameters outside the declared "
                   "hook region; ducking confined to [0,120)")


def f20_m04(ctx: CaseContext):
    """Interrupt fake music generation and resume; imported bed
    completes with provenance and zero generation charge."""
    db, arts, music, mix = _stack(ctx, "m04")
    gen = FakeMusicGen(ctx.run_dir / "m04-mus.json")
    music.generator = gen
    music.executor = Executor(db, provider=gen)
    gen.lose_next_submit()
    req = {"kind": "music", "brief": {"energy": "high"}}
    att = approve_operation(db, music.executor, req, "job:m04", kind="music", provider="google_music", model="fake-music", unit="usd_micros")
    try:
        music.executor.submit(att, lambda: gen.submit(req))
        ctx.check("interrupt_named", False)
    except ProviderError:
        ctx.check("interrupt_named", True)
    ctx.check("no_duplicate",
              len(gen.doc["ops"]) == 1,
              "one remote op; recovery reconciles, never resubmits")
    rec = music.recover("bed-g", operation_id=list(gen.doc["ops"])[0],
                        model_ref="fake-music-v1", now=NOW)
    ctx.check("recovered", rec["status"] in
              ("collected", "running", "accepted"))
    # imported bed: explicit provenance, no generation op
    src = _src(arts, key="import-src")
    bed = music.import_bed("bed-i", src.id,
                           license_ref="license:epidemic-99", now=NOW)
    ctx.check("imported_provenance",
              bed.source == "imported"
              and bed.provenance == "license:epidemic-99"
              and len(gen.doc["ops"]) == 1,
              "no charge for the imported path")
    return _result(ctx, "passed",
                   "interrupted generation reconciled to one op; "
                   "imported bed carries license provenance with no "
                   "generation charge")


def implementations():
    return {"F20-M01": f20_m01, "F20-M02": f20_m02,
            "F20-M03": f20_m03, "F20-M04": f20_m04}
