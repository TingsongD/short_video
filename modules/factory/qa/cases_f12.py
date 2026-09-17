from modules.factory.testing.authority import FixtureEffects
"""F12 manual scenarios: six-beat blueprint, long-haul structure,
honest unknowns, and interrupt/edit recovery."""
import json
import shutil
from pathlib import Path

from .cases_f01 import CaseContext, _result
from ..analysis import AnalysisService, BlueprintReview
from ..artifacts import ArtifactStore
from ..domain.errors import ContractError
from ..execution import Executor
from ..seeds import SeedRegistry
from ..store import Database
from ..testing.fakes import FakeAnalyzer, ProviderError
from ..testing.fixtures import materialize

FIX = Path("tests/factory_fixtures")
ROLES = ["hook", "product_reveal", "product_reveal",
         "product_reveal", "proof", "cta"]


def _scripted(transcript_path):
    data = json.loads(transcript_path.read_text())
    beats = [{"id": t["id"], "role": ROLES[i],
              "start_s": s[0], "end_s": s[1],
              "visual_event": f"scene_{i}", "confidence": "reviewed"}
             for i, (s, t) in enumerate(
                 zip(data["beats_s"], data["transcript"]))]
    return {"beats": beats, "transcript": data["transcript"],
            "music": {"role": "bed"}, "uncertainty": []}


def _stack(ctx, name, script=None):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-artifacts", db=db)
    reg = SeedRegistry(db, arts)
    analyzer = FakeAnalyzer(name, ctx.workspace.dir("fake_remote"),
                            ctx.workspace.ids, ctx.clock,
                            scripts=script or {})
    ex = Executor(db, analyzer, ctx.clock)
    return (db, arts, reg, analyzer, ex,
            AnalysisService(db, reg, arts, ex, analyzer, effects=FixtureEffects(db, ex)))


def _seed_with_media(reg, arts, fixture_root, media, url_id):
    import hashlib
    sha = hashlib.sha256(Path(media).read_bytes()).hexdigest()
    seed, _ = reg.submit_url(
        f"https://www.youtube.com/watch?v={url_id}")
    art = arts.intake_file(media, provenance="seed_source",
                           source_key=url_id, requested_kind="video")
    reg.attach_media(seed.id, art.id)
    return seed, sha


def f12_m01(ctx: CaseContext):
    """Analyze core-30s: six beats, transcript, boundaries — then
    reviewer correction and acceptance of the exact revision."""
    fx = ctx.run_dir / "m01-fx"
    materialize("core-30s", fx)
    root = fx / "fixtures" / "core-30s"
    script_media = _scripted(root / "transcript.json")
    import hashlib
    sha = hashlib.sha256((root / "source.mp4").read_bytes()).hexdigest()
    db, arts, reg, an, ex, svc = _stack(ctx, "m01", {sha: script_media})
    seed, _ = _seed_with_media(reg, arts, root, root / "source.mp4",
                               "core30s0000")
    bp = svc.analyze(seed.id)
    ctx.check("six_beats", len(bp.beats) == 6)
    ctx.check("beats_have_timecodes",
              all(b.source and b.target for b in bp.beats))
    ctx.check("tiles_900",
              bp.target_frames == 900 and bp.beats[-1].target.end == 900)
    ctx.check("transcript_present", len(bp.speech["transcript"]) == 6)
    ctx.check("evidence_per_beat",
              all(b.evidence_ids for b in bp.beats))
    review = BlueprintReview(db)
    ctx.check("no_flags", review.flags(bp.id) == [])
    accepted = review.accept(bp.id, bp.content_hash, reviewer="devin")
    ctx.check("accepted_exact_revision",
              accepted.status == "accepted")
    return _result(ctx, "awaiting_manual_review",
                   "six beats tile 900 frames with transcript + evidence "
                   "frames; accepted at the reviewed content hash",
                   limitations=["human watches/listens to source vs the "
                                "six proposed boundaries"])


def f12_m02(ctx: CaseContext):
    """Analyze long-haul-1697: full 169.7 s survives, first/last frame
    + product transitions preserved, no forced short template."""
    fx = ctx.run_dir / "m02-fx"
    materialize("long-haul-1697", fx)
    src = fx / "fixtures" / "long-haul-1697" / "source.mp4"
    dur = 169.7
    # 20 takes ≈ 8.5 s each — scripted beats covering the whole haul
    n = 20
    step = dur / n
    beats = [{"id": f"take-{i+1:02d}", "role": "product_reveal",
              "start_s": i * step, "end_s": (i + 1) * step,
              "visual_event": f"take_{i+1}", "confidence": "reviewed"}
             for i in range(n - 1)]
    beats.append({"id": "cta-final", "role": "cta",
                  "start_s": (n - 1) * step, "end_s": dur,
                  "visual_event": "final_cta", "confidence": "reviewed"})
    import hashlib
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    db, arts, reg, an, ex, svc = _stack(
        ctx, "m02", {sha: {"beats": beats, "transcript": [],
                          "music": {"role": "bed"},
                          "uncertainty": []}})
    seed, _ = _seed_with_media(reg, arts, fx, src, "longhaul000")
    bp = svc.analyze(seed.id)
    ctx.check("twenty_beats", len(bp.beats) == 20)
    ctx.check("full_duration_frames",
              bp.target_frames == 5091,  # 169.7 s * 30
              f"target_frames={bp.target_frames}")
    ctx.check("final_cta_present", bp.beats[-1].role == "cta"
              and bp.beats[-1].target.end == 5091)
    ctx.check("first_frame_covered", bp.beats[0].target.start == 0)
    return _result(ctx, "awaiting_manual_review",
                   "169.7 s / 20-take structure maps to 5091 frames; "
                   "final CTA is the last beat — no forced 30 s template",
                   limitations=["human spot-checks first/last frame and "
                                "product transitions against source"])


def f12_m03(ctx: CaseContext):
    """Missing audio + uncertain scenes: facts stay unknown; review
    does not auto-pass a generic verdict."""
    fx = ctx.run_dir / "m03-fx"
    materialize("reference-defects", fx)
    src = fx / "fixtures" / "reference-defects" / "missing_audio.mp4"
    db, arts, reg, an, ex, svc = _stack(ctx, "m03")   # default script
    seed, _ = _seed_with_media(reg, arts, fx, src, "noaudio1000")
    bp = svc.analyze(seed.id)
    ctx.check("audio_absent_fact", bp.audio["present"] is False)
    ctx.check("speech_unknown", bp.audio["speech"] == "unknown")
    ctx.check("music_unknown", bp.audio["music_role"] == "unknown")
    review = BlueprintReview(db)
    flags = [f["flag"] for f in review.flags(bp.id)]
    ctx.check("flags_named",
              "audio_missing" in flags and "low_confidence_scene" in flags,
              str(flags))
    try:
        review.accept(bp.id, bp.content_hash)
        ctx.check("accept_blocked", False)
    except ContractError as e:
        ctx.check("accept_blocked", e.code == "unresolved_flags")
    return _result(ctx, "passed",
                   "unknown speech/music stay unknown; mandatory review "
                   "blocked on named flags, not a model verdict")


def f12_m04(ctx: CaseContext):
    """Interrupt analysis → resume → edit a boundary after acceptance:
    one remote op, new revision, dependents marked stale."""
    fx = ctx.run_dir / "m04-fx"
    materialize("core-30s", fx)
    root = fx / "fixtures" / "core-30s"
    script_media = _scripted(root / "transcript.json")
    import hashlib
    sha = hashlib.sha256((root / "source.mp4").read_bytes()).hexdigest()
    db, arts, reg, an, ex, svc = _stack(ctx, "m04", {sha: script_media})
    seed, _ = _seed_with_media(reg, arts, root, root / "source.mp4",
                               "core30s0000")
    orig = an.submit
    def lost(request, faults=(), price=None):
        return orig(request, faults=("accept-then-timeout",),
                    price=price)
    an.submit = lost
    try:
        svc.analyze(seed.id)
        ctx.check("interrupt_raised", False)
    except ProviderError:
        ctx.check("interrupt_raised", True)
    an.submit = orig
    report = ex.recover()
    ctx.check("reconciled_one", len(report["reconciled"]) == 1)
    bp = svc.resume(report["reconciled"][0])
    ctx.check("no_resubmit",
              len(an.state.doc["operations"]) == 1)
    review = BlueprintReview(db)
    review.accept(bp.id, bp.content_hash)
    def move_boundary(body):
        body["beats"][1]["target"]["start_frame"] += 6
        body["beats"][1]["target"]["end_frame"] += 6
        body["beats"][0]["target"]["end_frame"] += 6
        return body
    out = review.edit(bp.id, move_boundary,
                      reason="shift beat boundary by 6 frames")
    ctx.check("new_revision", out["blueprint"].revision == 2)
    ctx.check("parent_linked",
              out["blueprint"].parent_hash == bp.content_hash)
    old = svc.get(bp.id, revision=1)
    ctx.check("old_superseded", old.status == "superseded")
    return _result(ctx, "passed",
                   "lost-ack attempt reconciled and resumed to a "
                   "blueprint; post-acceptance edit produced revision 2 "
                   "with parent hash; rev 1 superseded")


def implementations():
    return {"F12-M01": f12_m01, "F12-M02": f12_m02,
            "F12-M03": f12_m03, "F12-M04": f12_m04}
