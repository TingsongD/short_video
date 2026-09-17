"""F20: music beds + shared mix — exact durations, loop joins,
measured levels, clip policy, frozen profiles, unchanged-region
evidence, generation recovery, import provenance."""
import pytest

from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.audio import MixService, MusicService, pcm
from modules.factory.domain.errors import ContractError
from modules.factory.execution import Executor
from modules.factory.store import Database
from modules.factory.testing.fakes import (FakeAudioAnalyzer,
                                           FakeMusicGen, ProviderError,
                                           _wav_bytes)

NOW = "2026-09-17T00:00:00Z"


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "arts", db)
    music = MusicService(db, arts, analyzer=FakeAudioAnalyzer())
    mix = MixService(db, arts)
    return db, arts, music, mix, tmp_path


def _source_art(arts, tmp, seconds=6.0, freq=110.0):
    art = arts.intake_bytes(_wav_bytes(seconds, freq=freq),
                            provenance="manual", source_key="bed-src",
                            requested_kind="audio")
    return art


def test_import_bed_preserves_license(stack):
    db, arts, music, _, tmp = stack
    art = _source_art(arts, tmp)
    bed = music.import_bed("bed-1", art.id,
                           license_ref="license:epidemic-1234", now=NOW)
    assert bed.source == "imported"
    assert bed.provenance == "license:epidemic-1234"
    assert bed.bpm is None or bed.bpm == 120     # analyzer injected


def test_construct_exact_duration(stack):
    db, arts, music, _, tmp = stack
    art = _source_art(arts, tmp, seconds=6.0)
    music.import_bed("bed-1", art.id, license_ref="lic", now=NOW)
    out = music.construct_bed("bed-1", 30.0)
    assert out["construction"]["exact_samples"] == \
        out["measured"]["samples"]
    assert abs(out["measured"]["duration_s"] - 30.0) < 0.01
    # 6s source into 30s → 6 loops, 5 inspected joins
    assert out["construction"]["joins_inspected"] == 5
    out2 = music.construct_bed("bed-1", 169.7)
    assert abs(out2["measured"]["duration_s"] - 169.7) < 0.01


def test_construct_deterministic(stack):
    db, arts, music, _, tmp = stack
    art = _source_art(arts, tmp, seconds=4.0)
    music.import_bed("bed-1", art.id, license_ref="lic", now=NOW)
    a = music.construct_bed("bed-1", 12.0)
    # rebuild from a fresh bed id on same source → identical plan
    music.import_bed("bed-2", art.id, license_ref="lic", now=NOW)
    b = music.construct_bed("bed-2", 12.0)
    assert a["measured"]["samples"] == b["measured"]["samples"]


def test_freeze_profile_and_mix(stack):
    db, arts, music, mix, tmp = stack
    art = _source_art(arts, tmp, seconds=8.0)
    music.import_bed("bed-1", art.id, license_ref="lic", now=NOW)
    prof = mix.freeze("mp-1", "exp1", "bed-1", {
        "loudness_target": {"rms_dbfs": -16.0,
                            "basis": "fixture qualification"},
        "music_gain_db": -14.0}, now=NOW)
    assert prof.status == "frozen" and prof.profile_hash
    speech = pcm.sine(2.0, freq=440.0, amp=10000)
    out = mix.mix("mp-1", [
        {"artifact_id": art.id, "kind": "music", "offset_s": 0.0},
        {"samples": speech, "kind": "speech", "offset_s": 1.0}],
        out_s=8.0, artifact_name="mixA")
    assert out["measured"]["rms_dbfs"] is not None
    assert out["artifact_id"] and out["exact_samples"] == 8 * pcm.RATE


def test_over_loud_clip_repair_documented(stack):
    db, arts, music, mix, tmp = stack
    art = _source_art(arts, tmp, seconds=4.0)
    music.import_bed("bed-1", art.id, license_ref="lic", now=NOW)
    mix.freeze("mp-1", "exp1", "bed-1", {"music_gain_db": 20.0},
               now=NOW)
    out = mix.mix("mp-1", [{"artifact_id": art.id, "kind": "music",
                            "offset_s": 0.0}], out_s=4.0)
    # policy=prevent → documented gain repair, not silent passthrough
    assert out["clipped"] is False
    assert "repaired_db" in out["measured"]


def test_missing_music_explicit(stack):
    db, arts, music, mix, tmp = stack
    mix.freeze("mp-1", "exp1", "bed-x", {}, now=NOW)
    with pytest.raises(ContractError, match="unknown_artifact"):
        mix.mix("mp-1", [{"artifact_id": "art:missing",
                          "kind": "music", "offset_s": 0.0}], out_s=1.0)


def test_unchanged_region_identical(stack):
    db, arts, music, mix, tmp = stack
    cfg = {"music_gain_db": -14.0,
           "duck": {"enabled": True, "amount_db": 8.0,
                    "regions": [{"start": 0, "end": 120}]}}
    mix.freeze("mp-a", "exp1", "bed-1", dict(cfg), now=NOW)
    mix.freeze("mp-b", "exp1", "bed-1", dict(cfg), now=NOW)
    unchanged = [{"start_frame": 120, "end_frame": 900}]
    assert mix.assert_unchanged_identical("mp-a", "mp-b", unchanged)


def test_unchanged_region_diff_detected(stack):
    db, arts, music, mix, tmp = stack
    mix.freeze("mp-a", "exp1", "bed-1", {"music_gain_db": -14.0},
               now=NOW)
    mix.freeze("mp-b", "exp1", "bed-1", {"music_gain_db": -20.0},
               now=NOW)
    with pytest.raises(ContractError, match="unchanged_region_differs"):
        mix.assert_unchanged_identical(
            "mp-a", "mp-b", [{"start_frame": 0, "end_frame": 900}])


def test_generate_and_recover(stack):
    db, arts, music, mix, tmp = stack
    gen = FakeMusicGen(tmp / "mus.json")
    music.generator = gen
    music.executor = Executor(db, provider=gen)
    out = music.generate("bed-g", "job:mus", {"energy": "high"})
    music.collect("bed-g", out["operation"]["operation_id"], "fake-music-v1", now=NOW)
    got = music.collect("bed-g", out["operation"]["operation_id"],
                        "fake-music-v1", now=NOW)
    assert got["status"] == "collected"
    assert got["bed"]["provenance"] == "fake-music-v1"
    assert got["bed"]["bpm"] == 120


def test_generation_route_auth_distinct(stack):
    db, arts, music, _, tmp = stack
    gen = FakeMusicGen(tmp / "mus.json", authed=False)
    music.generator = gen
    music.executor = Executor(db, provider=gen)
    with pytest.raises(ProviderError, match="route_auth_required"):
        music.generate("bed-g", "job:mus", {})


def test_generate_lost_ack_recovers(stack):
    db, arts, music, _, tmp = stack
    gen = FakeMusicGen(tmp / "mus.json")
    music.generator = gen
    music.executor = Executor(db, provider=gen)
    gen.lose_next_submit()
    import json, hashlib
    req = {"kind": "music", "brief": {"energy": "high"}}
    att = music.executor.prepare("job:m", 1, req, kind="music_generation",
                                 provider="fake_music")
    with pytest.raises(ProviderError):
        music.executor.submit(att, lambda: gen.submit(req))
    assert len(gen.doc["ops"]) == 1
    rec = music.recover("bed-g", operation_id=list(gen.doc["ops"])[0],
                        model_ref="fake-music-v1", now=NOW)
    assert rec["status"] in ("collected", "running", "accepted")
    assert len(gen.doc["ops"]) == 1
