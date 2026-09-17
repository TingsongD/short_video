"""F12 — reference analysis and blueprint review."""
import hashlib
import json
from pathlib import Path

import pytest

from modules.factory.analysis import (
    AnalysisService, BlueprintReview, parse_analysis)
from modules.factory.analysis.service import blueprint_id_for
from modules.factory.artifacts import ArtifactStore
from modules.factory.domain.clocks import FPS_30
from modules.factory.domain.errors import ContractError
from modules.factory.execution import Executor
from modules.factory.seeds import SeedRegistry
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeAnalyzer, ProviderError
from modules.factory.testing.fixtures import materialize
from modules.factory.testing.ids import IdFactory

FIX = Path("tests/factory_fixtures")


def _scripted(fixture):
    """Build an analyzer script from a fixture's transcript.json."""
    data = json.loads(fixture.read_text())
    beats = []
    roles = ["hook", "product_reveal", "product_reveal",
             "product_reveal", "proof", "cta"]
    for i, (span, t) in enumerate(
            zip(data["beats_s"], data["transcript"])):
        beats.append({"id": t["id"], "role": roles[i],
                      "start_s": span[0], "end_s": span[1],
                      "visual_event": f"scene_{i}",
                      "confidence": "reviewed"})
    return {"beats": beats, "transcript": data["transcript"],
            "music": {"role": "bed"}, "uncertainty": []}


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    arts = ArtifactStore(tmp_path / "artifacts", db=db)
    reg = SeedRegistry(db, arts)
    fx = tmp_path / "fx"
    materialize("core-30s", fx)
    src = fx / "fixtures" / "core-30s" / "source.mp4"
    script = _scripted(fx / "fixtures" / "core-30s" / "transcript.json")
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    analyzer = FakeAnalyzer("av", tmp_path / "remote",
                            IdFactory(tmp_path / "ids.json"),
                            FakeClock(), scripts={sha: script})
    ex = Executor(db, analyzer, FakeClock())
    svc = AnalysisService(db, reg, arts, ex, analyzer)
    seed, _ = reg.submit_url("https://www.youtube.com/watch?v=core30s0000")
    art = arts.intake_file(src, provenance="seed_source",
                           source_key="core-30s", requested_kind="video")
    reg.attach_media(seed.id, art.id)
    return {"db": db, "arts": arts, "reg": reg, "svc": svc, "ex": ex,
            "analyzer": analyzer, "seed": seed, "src": src, "sha": sha,
            "fx": fx}


class TestAnalysis:
    def test_six_beat_blueprint_tiles_target(self, env):
        bp = env["svc"].analyze(env["seed"].id)
        assert len(bp.beats) == 6
        assert bp.target_frames == 900           # 30 s @ 30 fps
        assert bp.beats[0].target.start == 0
        assert bp.beats[-1].target.end == 900
        ivs = [b.target for b in bp.beats]
        for a, b in zip(ivs, ivs[1:]):
            assert a.adjacent(b)                 # no gaps/overlaps

    def test_evidence_links_and_speech(self, env):
        bp = env["svc"].analyze(env["seed"].id)
        for b in bp.beats:
            assert b.evidence_ids               # frame artifact + scenes
            aid = b.evidence_ids[0]
            assert env["arts"].path_for(aid).is_file()
        hook = bp.beats[0]
        assert hook.speech_segment_id == "hook"
        assert bp.speech["observed_source_text"] is True
        assert bp.adaptation["requires_new_copy"] is True
        # source file untouched — byte-identical after analysis
        now = hashlib.sha256(env["src"].read_bytes()).hexdigest()
        assert now == env["sha"]

    def test_target_frame_mapping_exact(self, env):
        bp = env["svc"].analyze(env["seed"].id)
        # beat 4 (proof): 17 s → frame 510 at 30 fps
        proof = next(b for b in bp.beats if b.role == "proof")
        assert (proof.target.start, proof.target.end) == (510, 780)

    def test_thumbnail_source_refused(self, env):
        fx = env["fx"]
        materialize("reference-defects", fx)
        img = env["arts"].intake_file(
            fx / "fixtures" / "reference-defects" / "thumbnail_as_video.mp4",
            provenance="seed_source", source_key="thumb")
        assert img.kind == "image"
        seed, _ = env["reg"].submit_url(
            "https://www.youtube.com/watch?v=thumbseed00")
        # bypass attach_media's kind check — an image artifact must still
        # be refused at analysis time even if attached by a bad path
        with env["db"].uow() as u:
            bad = env["reg"].get(seed.id)
            bad.source_asset_id = img.id
            bad.evidence_status = "media_ready"
            bad.revision += 1
            u.records.put(bad)
        with pytest.raises(ContractError) as e:
            env["svc"].analyze(seed.id)
        assert e.value.code == "source_not_video"

    def test_malformed_analysis_typed(self, env):
        env["analyzer"].scripts[env["sha"]] = {"beats": "garbage"}
        # malformed script → parse_analysis raises
        with pytest.raises(ContractError) as e:
            parse_analysis(env["analyzer"].scripts[env["sha"]])
        assert e.value.code == "malformed_analysis"

    def test_missing_audio_stays_unknown(self, env):
        fx = env["fx"]
        materialize("reference-defects", fx)
        src = fx / "fixtures" / "reference-defects" / "missing_audio.mp4"
        seed, _ = env["reg"].submit_url(
            "https://www.youtube.com/watch?v=noaudio1000")
        art = env["arts"].intake_file(src, provenance="seed_source",
                                    source_key="noaudio",
                                    requested_kind="video")
        env["reg"].attach_media(seed.id, art.id)
        bp = env["svc"].analyze(seed.id)
        assert bp.audio["present"] is False
        assert bp.audio["speech"] == "unknown"
        flags = BlueprintReview(env["db"]).flags(bp.id)
        assert any(f["flag"] == "audio_missing" for f in flags)


class TestReview:
    def test_flags_block_acceptance(self, env):
        bp = env["svc"].analyze(env["seed"].id)
        # default-script confidence is "uncertain" → flagged; our script
        # is "reviewed" so flags should be empty here
        review = BlueprintReview(env["db"])
        assert review.flags(bp.id) == []
        acc = review.accept(bp.id, bp.content_hash, reviewer="qa")
        assert acc.status == "accepted"

    def test_accept_hash_mismatch(self, env):
        bp = env["svc"].analyze(env["seed"].id)
        review = BlueprintReview(env["db"])
        with pytest.raises(ContractError) as e:
            review.accept(bp.id, "deadbeef")
        assert e.value.code == "revision_mismatch"

    def test_uncertain_beats_flagged(self, env):
        env["analyzer"].scripts.pop(env["sha"])     # default → uncertain
        bp = env["svc"].analyze(env["seed"].id)
        flags = BlueprintReview(env["db"]).flags(bp.id)
        assert any(f["flag"] == "low_confidence_scene" for f in flags)
        with pytest.raises(ContractError):
            BlueprintReview(env["db"]).accept(bp.id, bp.content_hash)

    def test_edit_creates_child_and_stales_dependents(self, env):
        bp = env["svc"].analyze(env["seed"].id)
        review = BlueprintReview(env["db"])
        review.accept(bp.id, bp.content_hash)
        # bind a template to this blueprint hash
        from modules.factory.domain.records import FormatTemplate
        with env["db"].uow() as u:
            u.records.put(FormatTemplate(
                schema_version="format_template.v1", id="ft-1",
                created_at="2026-09-16T00:00:00Z", revision=1,
                derived_from_blueprint=bp.content_hash))

        def mutate(body):
            body["beats"][0]["role"] = "product_reveal"
            return body
        out = review.edit(bp.id, mutate, reason="fix first beat role")
        child = out["blueprint"]
        assert child.revision == 2 and child.parent_hash == bp.content_hash
        assert "ft-1" in out["stale_dependents"]
        old = env["svc"].get(bp.id, revision=1)
        assert old.status == "superseded"


class TestRecovery:
    def test_interrupted_analysis_resumes_same_op(self, env):
        # kill the ack: submit raises after acceptance
        orig = env["analyzer"].submit
        def lost(request, faults=(), price=None):
            return orig(request, faults=("accept-then-timeout",),
                        price=price)
        env["analyzer"].submit = lost
        with pytest.raises(ProviderError):
            env["svc"].analyze(env["seed"].id)
        env["analyzer"].submit = orig
        report = env["ex"].recover()
        assert len(report["reconciled"]) == 1
        att = report["reconciled"][0]
        bp = env["svc"].resume(att)
        assert len(bp.beats) == 6
        # exactly one remote op exists — no resubmission
        assert len(env["analyzer"].state.doc["operations"]) == 1

    def test_word_outside_segment_is_malformed(self):
        bad = {"beats": [{"id": "b", "role": "hook", "start_s": 0,
                          "end_s": 2, "confidence": "reviewed"}],
               "transcript": [{"id": "t", "text": "hi", "start_s": 0,
                               "end_s": 2,
                               "words": [{"text": "hi", "start_s": 0,
                                          "end_s": 9}]}]}
        with pytest.raises(ContractError) as e:
            parse_analysis(bad)
        assert "outside segment" in e.value.detail
