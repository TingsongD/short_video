"""Mandatory deep-analysis gate — preliminary observations, stale
bindings, bypass paths, non-speech sources, resume, captions."""
import json
from pathlib import Path

import pytest

from modules.factory.bootstrap import bootstrap
from modules.factory.analysis.deep import (
    ReferenceAnalysisService, analysis_gate, bound_gate,
    analysis_id_for)
from modules.factory.analysis.review import BlueprintReview
from modules.factory.domain.errors import ContractError
from modules.factory.testing.fixtures import _moving_mp4
from modules.factory.store.uow import utcnow
from test_factory_application import (
    FakeHypit, seed_completed_analysis)


@pytest.fixture
def env(tmp_path):
    s = bootstrap(tmp_path)
    return {"s": s, "root": tmp_path}


def _seed(env, seconds=3, audio=True, url="https://youtu.be/abcdefghijk",
          captions=None):
    s, root = env["s"], env["root"]
    src = root / f"src-{audio}-{seconds}.mp4"
    _moving_mp4(src, seconds, size="180x320", audio=audio)
    seed, _ = s.seeds.submit_url(url)
    if captions:
        with s.db.uow() as u:
            row = s.seeds.get(seed.id)
            row.metadata = {**(row.metadata or {}), "captions": captions}
            row.revision += 1
            u.records.put(row)
    art = s.artifacts.intake_file(src, provenance="seed_source",
                                  source_key=f"{audio}-{seconds}",
                                  requested_kind="video")
    s.seeds.attach_media(seed.id, art.id)
    return seed, art


def _blueprint(s, seed_id, seconds=3):
    obs = {"beats": [{"id": f"b{i}", "role": r,
                      "start_s": i * seconds / 3,
                      "end_s": (i + 1) * seconds / 3,
                      "confidence": "reviewed",
                      "visual_event": "x"} for i, r in
                     enumerate(("hook", "body", "cta"))],
           "transcript": [{"id": "speech", "start_s": 0,
                           "end_s": seconds,
                           "text": "source reference"}],
           "music": {"role": "bed"}}
    return s.analysis.import_observations(seed_id, obs, "qa")


def _sections(svc, seed_id, seconds=3):
    fields = {f: f"{f} reading" for f in
              ("premise", "progression", "hook", "setups", "payoffs",
               "ending", "replay_appeal", "intended_response")}
    fields["observations"] = ["dog misses the ball"]
    fields["interpretations"] = ["the miss is the joke"]
    fields["uncertainties"] = ["staged?"]
    svc.save_understanding(seed_id, fields, "qa")
    span = seconds / 3
    svc.save_timeline(seed_id, [
        {"start_s": i * span, "end_s": (i + 1) * span, "phase": p,
         "summary": f"{p} part"}
        for i, p in enumerate(("hook", "body", "payoff"))], "qa")
    svc.save_treatment(seed_id, {f: f"{f} note" for f in
                                 ("summary", "preserves", "redesigns",
                                  "script_direction")}, "qa")


def _complete(env, seed, seconds=3, hypit=None):
    svc = env["s"].ref_analysis
    svc.hypit = hypit or FakeHypit()
    svc.start(seed.id, "qa")
    svc.run_machine_stages(seed.id)
    _sections(svc, seed.id, seconds)
    return svc.review(seed.id, "qa", "accept")


def test_timeline_middle_and_edge_gaps_rejected(env):
    """Three probe instants used to pass sections with a hole in the
    middle; coverage is now the union of the intervals."""
    seed, _ = _seed(env, seconds=9)
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit()
    svc.start(seed.id, "qa")
    svc.run_machine_stages(seed.id)
    fields = {f: f"{f} reading" for f in
              ("premise", "progression", "hook", "setups", "payoffs",
               "ending", "replay_appeal", "intended_response")}
    fields["observations"] = ["x"]
    fields["interpretations"] = ["y"]
    svc.save_understanding(seed.id, fields, "qa")
    ok = [{"start_s": 0, "end_s": 3, "phase": "a", "summary": "s"},
          {"start_s": 3, "end_s": 6, "phase": "b", "summary": "s"},
          {"start_s": 6, "end_s": 9, "phase": "c", "summary": "s"}]
    svc.save_timeline(seed.id, ok, "qa")
    for bad in (
            # hole in the middle — the old 0/dur/2/dur probes sat inside
            # the outer sections and passed
            [{"start_s": 0, "end_s": 2, "phase": "a", "summary": "s"},
             {"start_s": 7, "end_s": 9, "phase": "b", "summary": "s"}],
            # uncovered tail
            [{"start_s": 0, "end_s": 3, "phase": "a", "summary": "s"},
             {"start_s": 3, "end_s": 6, "phase": "b", "summary": "s"}],
            # uncovered head
            [{"start_s": 2, "end_s": 5, "phase": "a", "summary": "s"},
             {"start_s": 5, "end_s": 9, "phase": "b", "summary": "s"}],
            # substantial overlap inside the span
            [{"start_s": 0, "end_s": 6, "phase": "a", "summary": "s"},
             {"start_s": 2, "end_s": 5, "phase": "b", "summary": "s"},
             {"start_s": 6, "end_s": 9, "phase": "c", "summary": "s"}]):
        with pytest.raises(ContractError) as e:
            svc.save_timeline(seed.id, bad, "qa")
        assert e.value.code == "timeline_coverage_required"


# ------------------------------------------------------------ gate

def test_accept_blocked_without_analysis(env):
    seed, _ = _seed(env)
    bp = _blueprint(env["s"], seed.id)
    with pytest.raises(ContractError) as e:
        BlueprintReview(env["s"].db).accept(bp.id, bp.content_hash, "qa")
    assert e.value.code == "analysis_required"


def test_incomplete_analysis_blocked(env):
    seed, _ = _seed(env)
    bp = _blueprint(env["s"], seed.id)
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit()
    svc.start(seed.id, "qa")                     # stages never run
    with pytest.raises(ContractError) as e:
        BlueprintReview(env["s"].db).accept(bp.id, bp.content_hash, "qa")
    assert e.value.code == "analysis_incomplete"


def test_full_flow_binds_and_accepts(env):
    seed, _ = _seed(env)
    bp = _blueprint(env["s"], seed.id)
    a = _complete(env, seed)
    assert a.status == "complete"
    acc = BlueprintReview(env["s"].db).accept(
        bp.id, bp.content_hash, "qa")
    assert acc.status == "accepted"
    assert acc.analysis == {"id": a.id, "revision": a.revision}
    # downstream paths now pass the binding gate
    tpl = env["s"].author_template({"blueprint_id": bp.id})
    assert tpl["id"].startswith("tpl-")


def test_preliminary_captions_cannot_satisfy_transcript(env):
    seed, _ = _seed(env, captions="auto caption text")
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit(whisperx=False)
    svc.start(seed.id, "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "blocked"
    assert a.transcript["preliminary"] is True
    assert a.transcript["status"] == "unavailable"
    with pytest.raises(ContractError) as e:
        svc.review(seed.id, "qa", "accept")
    assert e.value.code == "analysis_not_reviewable"
    bp = _blueprint(env["s"], seed.id)
    with pytest.raises(ContractError) as e:
        BlueprintReview(env["s"].db).accept(bp.id, bp.content_hash, "qa")
    assert e.value.code == "analysis_blocked"


def test_imported_transcript_recovers_blocked(env):
    seed, _ = _seed(env, captions="auto caption text")
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit(whisperx=False)
    svc.start(seed.id, "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "blocked"
    svc.import_transcript(seed.id, {
        "provider": "external_whisperx", "provenance": "operator-run "
        "whisperx large-v3 on the verified source bytes",
        "confidence": "word-level",
        "words": [{"word": "dog", "start_s": 0.0, "end_s": 0.4},
                  {"word": "ball", "start_s": 0.5, "end_s": 1.0}],
        "reviewer": "qa"}, "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "evidence_ready"
    _sections(svc, seed.id)
    a = svc.review(seed.id, "qa", "accept")
    assert a.status == "complete"


def test_transcribe_available_reads_programs_status():
    """The capability probe must read `programs status` (which names
    profile endpoints) — `runtime status` carries worker counts only,
    so a grepped 'whisperx' there always misses a configured service."""
    from modules.factory.analysis.deep import HypitTransport

    calls = []

    def runner(argv, timeout=600):
        calls.append(argv[1:])
        out = json.dumps({"profileSource": "project"}) \
            if "paths" in argv else json.dumps({
                "programs": [{"endpoint": "media.local",
                              "state": "ready"},
                             {"endpoint": "whisperx.local",
                              "state": "ready"}]})
        return type("R", (), {"returncode": 0, "stdout": out,
                              "stderr": ""})()

    h = HypitTransport("/nonexistent-hypit", runner=runner)
    assert h.transcribe_available() is True
    assert ["programs", "status", "--json"] in calls

    def runner_no_profile(argv, timeout=600):
        return type("R", (), {"returncode": 0, "stderr": "",
                              "stdout": json.dumps(
                                  {"profileSource": "none"})})()
    h2 = HypitTransport("/x", runner=runner_no_profile)
    assert h2.transcribe_available() is False


def test_imported_transcript_file_is_hypit_readable(env):
    """The written transcript.json must satisfy the real
    `hypit media tiles --transcript` contract — format
    hypit.transcript@1 with passages of timed words — or the
    evidence stage blocks with 'expected hypit.transcript@1'."""
    seed, _ = _seed(env, seconds=8, captions="auto caption text")
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit(whisperx=False)
    svc.start(seed.id, "qa")
    svc.run_machine_stages(seed.id)
    svc.import_transcript(seed.id, {
        "provider": "external_whisperx", "provenance": "operator-run "
        "whisperx large-v3 on the verified source bytes",
        "words": [{"word": "dog", "start_s": 0.0, "end_s": 0.4},
                  {"word": "ball", "start_s": 0.5, "end_s": 1.0},
                  {"word": "later", "start_s": 5.0, "end_s": 5.5}],
        "reviewer": "qa"}, "qa")
    a = svc.get(seed.id)
    doc = json.loads(Path(a.transcript["file"]).read_text())
    assert doc["format"] == "hypit.transcript@1"
    assert doc["imported_by"] == "external_whisperx"
    # gap >2s splits passages without inventing or losing words
    assert [len(p["words"]) for p in doc["passages"]] == [2, 1]
    flat = [w for p in doc["passages"] for w in p["words"]]
    assert [w["text"] for w in flat] == ["dog", "ball", "later"]
    for w in flat:
        assert 0 <= w["start_seconds"] <= w["end_seconds"]
    assert svc._transcript_words(a.transcript["file"]) == flat


def test_bad_import_transcript_rejected(env):
    seed, _ = _seed(env)
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit(whisperx=False)
    svc.start(seed.id, "qa")
    svc.run_machine_stages(seed.id)
    with pytest.raises(ContractError) as e:
        svc.import_transcript(seed.id, {
            "provider": "x", "provenance": "y",
            "words": [{"word": "late", "start_s": 99.0,
                       "end_s": 100.0}]}, "qa")
    assert e.value.code == "transcript_words_invalid"


def test_nonverbal_source_completes(env):
    seed, art = _seed(env, audio=False,
                      url="https://youtu.be/silent0000a")
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit(whisperx=False)
    svc.start(seed.id, "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "evidence_ready"          # never blocked
    assert a.transcript["status"] == "not_applicable"
    _sections(svc, seed.id)
    a = svc.review(seed.id, "qa", "accept")
    assert a.status == "complete"
    # the deep gate itself is satisfied — no invented transcript needed
    sha = env["s"].db.uow().artifacts.get(art.id)["sha256"]
    assert analysis_gate(env["s"].db, seed.id, sha).status == "complete"


def test_declared_nonverbal_recovers_speech_looking_media(env):
    seed, _ = _seed(env)
    svc = env["s"].ref_analysis
    svc.hypit = FakeHypit(whisperx=False)
    svc.start(seed.id, "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "blocked"
    svc.declare(seed.id, "declared_nonverbal",
                "instrumental bed only — reviewed overview grids and "
                "audio level, no speech events", "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "evidence_ready"


def test_stale_source_sha_blocks(env):
    seed, _ = _seed(env)
    _complete(env, seed)
    # different source bytes arrive later → new artifact, new sha
    src2 = env["root"] / "changed.mp4"
    _moving_mp4(src2, 4, size="180x320")
    art2 = env["s"].artifacts.intake_file(
        src2, provenance="seed_source", source_key="changed",
        requested_kind="video")
    env["s"].seeds.attach_media(seed.id, art2.id)
    bp = _blueprint(env["s"], seed.id, seconds=4)
    with pytest.raises(ContractError) as e:
        BlueprintReview(env["s"].db).accept(bp.id, bp.content_hash, "qa")
    assert e.value.code == "analysis_stale"


def test_edit_supersedes_and_stales_binding(env):
    seed, _ = _seed(env)
    bp = _blueprint(env["s"], seed.id)
    _complete(env, seed)
    BlueprintReview(env["s"].db).accept(bp.id, bp.content_hash, "qa")
    # an operator edit after acceptance opens revision 2
    svc = env["s"].ref_analysis
    fields = {f: f"{f} revised" for f in
              ("premise", "progression", "hook", "setups", "payoffs",
               "ending", "replay_appeal", "intended_response")}
    fields.update(observations=["o"], interpretations=["i"],
                  uncertainties=[])
    a2 = svc.save_understanding(seed.id, fields, "qa")
    assert a2.revision == 2
    # incomplete revision blocks downstream paths
    with pytest.raises(ContractError) as e:
        env["s"].author_template({"blueprint_id": bp.id})
    assert e.value.code == "analysis_incomplete"
    # complete r2 — binding is still pinned to r1 → stale
    _sections(svc, seed.id)
    svc.review(seed.id, "qa", "accept")
    with pytest.raises(ContractError) as e:
        env["s"].author_template({"blueprint_id": bp.id})
    assert e.value.code == "analysis_stale"
    # re-accept binds r2 → path clears again
    acc = BlueprintReview(env["s"].db).accept(bp.id, bp.content_hash, "qa")
    assert acc.analysis["revision"] == 2
    env["s"].author_template({"blueprint_id": bp.id})


def test_legacy_accepted_blueprint_fails_closed(env):
    """A blueprint accepted before the gate existed has no binding —
    downstream production must refuse it until reanalysis+reaccept."""
    seed, _ = _seed(env)
    bp = _blueprint(env["s"], seed.id)
    with env["s"].db.uow() as u:               # simulate legacy record
        u.conn.execute(
            "UPDATE records SET status='accepted',"
            " body=json_replace(body,'$.status','accepted')"
            " WHERE kind='referenceblueprint' AND id=?", (bp.id,))
    with pytest.raises(ContractError) as e:
        env["s"].author_template({"blueprint_id": bp.id})
    assert e.value.code == "analysis_required"
    # experiment path fails closed the same way — bind a template to
    # the legacy blueprint's hash so the flow reaches the gate
    from modules.factory.domain.records import FormatTemplate
    with env["s"].db.uow() as u:
        u.records.put(FormatTemplate(
            schema_version="format_template.v1", id="tpl-legacy",
            created_at=utcnow(), revision=1,
            derived_from_blueprint=bp.content_hash))
    with pytest.raises(ContractError) as e:
        env["s"].create_experiment_draft("exp-x", {
            "blueprint_id": bp.id, "template_id": "tpl-legacy",
            "segments": [], "variants": []})
    assert e.value.code == "analysis_required"


def test_bound_gate_unit_cases(env):
    seed, art = _seed(env)
    sha = env["s"].db.uow().artifacts.get(art.id)["sha256"]
    a = seed_completed_analysis(env["s"].db, seed.id, sha)
    good = {"id": a.id, "revision": 1}
    assert bound_gate(env["s"].db, seed.id, sha, good).id == a.id
    with pytest.raises(ContractError) as e:
        bound_gate(env["s"].db, seed.id, sha, {})
    assert e.value.code == "analysis_required"
    with pytest.raises(ContractError) as e:
        bound_gate(env["s"].db, seed.id, sha, {"id": a.id, "revision": 9})
    assert e.value.code == "analysis_stale"
    with pytest.raises(ContractError) as e:
        bound_gate(env["s"].db, seed.id, "0" * 64, good)
    assert e.value.code == "analysis_stale"


def test_incomplete_record_cannot_fake_complete(env):
    """status='complete' written by hand still fails the substantive
    completeness check — the flag alone is never sufficient."""
    seed, art = _seed(env)
    sha = env["s"].db.uow().artifacts.get(art.id)["sha256"]
    a = seed_completed_analysis(env["s"].db, seed.id, sha)
    with env["s"].db.uow() as u:                 # strip the evidence
        row = u.records.get("referenceanalysis", a.id, revision=1)
        body = json.loads(row["body"])
        body["evidence"] = {}
        u.conn.execute(
            "UPDATE records SET body=? WHERE kind='referenceanalysis'"
            " AND id=? AND revision=1", (json.dumps(body), a.id))
    with pytest.raises(ContractError) as e:
        analysis_gate(env["s"].db, seed.id, sha)
    assert e.value.code == "analysis_incomplete"


# ------------------------------------------------------------- resume

def test_interrupted_stages_resume_without_repeating_work(env):
    seed, _ = _seed(env)
    svc = env["s"].ref_analysis
    hypit = FakeHypit()

    class FlakyTiles(FakeHypit):
        def tiles(self, *a, **k):
            return type("R", (), {"returncode": 1,
                                  "stderr": "lost worker",
                                  "stdout": ""})()
    svc.hypit = FlakyTiles()
    svc.start(seed.id, "qa")
    a = svc.run_machine_stages(seed.id)
    assert a.status == "blocked"                 # died inside evidence
    assert a.stages["acquire"]["done"]
    assert a.stages["transcript"]["done"]        # paid call already made
    svc.hypit = hypit
    a = svc.run_machine_stages(seed.id)
    assert a.status == "evidence_ready"
    transcodes = [c for c in hypit.calls if c[0] == "transcribe"]
    # the transcript was checkpointed — never re-generated on resume
    assert transcodes == []
    assert [c for c in hypit.calls if c[0] == "boundaries"]


def test_completed_analysis_start_is_idempotent(env):
    seed, _ = _seed(env)
    a = _complete(env, seed)
    again = env["s"].ref_analysis.start(seed.id, "qa")
    assert again.revision == a.revision and again.status == "complete"


def test_documents_written_to_project(env):
    seed, _ = _seed(env)
    a = _complete(env, seed)
    root = Path(a.documents["root"])
    for key in ("analysis_md", "timeline_md", "treatment_md",
                "progress_md", "manifest"):
        p = Path(a.documents["files"][key])
        assert p.is_file() and str(p).startswith(str(root))
    text = Path(a.documents["files"]["analysis_md"]).read_text()
    assert "Verified acquisition" in text and a.source_sha256 in text
