"""Regression tests for the last-run investigation
(INVESTIGATION-auto-cd98a5cf5308471b). Each test pins a defect the live
run surfaced: timestamp validation, transcript quality, single-ownership
passage assignment, real A–D variation, frame-clock handling, provider
diagnostics, and worker ownership. All offline."""
import json
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from modules.factory.analysis.analyzer import (
    assign_passages, parse_analysis, validate_temporal)
from modules.factory.analysis.deep import transcript_problems
from modules.factory.autorun import scripts
from modules.factory.domain.errors import ContractError
from modules.factory.rendering.ffmpeg_fast import FastPathRenderer
from modules.factory.testing.fixtures import _moving_mp4


# ---------------------------------------------- temporal validation --

def _beats(*specs):
    return [{"id": f"b{i}", "role": "body", "start_s": s, "end_s": e,
             "confidence": "reviewed", "visual_event": "x"}
            for i, (s, e) in enumerate(specs)]


def _analysis(*specs, transcript=None):
    return {"beats": _beats(*specs),
            "transcript": transcript or [],
            "music": {"role": "bed"}, "uncertainty": []}


def test_incident_point_four_second_analysis_rejected():
    """The incident verbatim: provider beats covering 0.4s of a verified
    37.6s source. Coverage that stops materially short is structurally
    invalid — never stretched into place."""
    analysis = _analysis((0.0, 0.4))
    with pytest.raises(ContractError) as e:
        validate_temporal(analysis, 37.6)
    assert e.value.code == "invalid_analysis_timing"
    assert "unaccounted" in e.value.detail


def test_temporal_rejects_non_finite_overlap_gap_and_tiny_beats():
    bad = [
        _analysis((0.0, 3.0), (3.0, float("nan"))),          # non-finite
        _analysis((0.0, 5.0), (4.0, 9.0)),                  # overlap
        _analysis((0.0, 3.0), (5.0, 9.0)),                  # gap
        _analysis((0.0, 0.05), (0.05, 9.0)),                # tiny beat
        _analysis((0.0, 3.0), (3.0, 12.0)),                 # overruns media
        _analysis((2.0, 5.0), (5.0, 9.0)),                  # head missing
    ]
    for analysis in bad:
        with pytest.raises(ContractError) as e:
            validate_temporal(analysis, 9.0)
        assert e.value.code == "invalid_analysis_timing"


def test_temporal_bounded_tail_snap_is_the_only_correction():
    """Coverage ending within the tolerance snaps to the verified
    duration downstream; a larger shortfall stays a rejection."""
    ok = _analysis((0.0, 3.0), (3.0, 8.8))      # 0.2s short < 0.5 tol
    validate_temporal(ok, 9.0)                   # does not raise
    too_short = _analysis((0.0, 3.0), (3.0, 8.0))
    with pytest.raises(ContractError):
        validate_temporal(too_short, 9.0)


def test_temporal_allows_transcript_gaps_but_not_bad_order():
    a = _analysis((0.0, 4.5), (4.5, 9.0),
                  transcript=[{"id": "t0", "start_s": 1.0,
                               "end_s": 2.0, "text": "hi"},
                              {"id": "t1", "start_s": 6.0,
                               "end_s": 8.0, "text": "bye"}])
    validate_temporal(a, 9.0)                    # silence gaps are legal
    a["transcript"][1]["start_s"] = 0.5          # overlaps t0's span…
    a["transcript"][0]["end_s"] = 4.0            # …materially
    with pytest.raises(ContractError):
        validate_temporal(a, 9.0)


# ------------------------------------------------ passage ownership --

def test_passage_spanning_a_boundary_is_owned_exactly_once():
    """A passage crossing a beat boundary was previously copied into
    BOTH beats. Single ownership: the beat containing its start."""
    beats = _beats((0.0, 3.0), (3.0, 6.0), (6.0, 9.0))
    transcript = [{"id": "t0", "start_s": 2.0, "end_s": 4.0,
                   "text": "crosses the seam"}]
    out = assign_passages(beats, transcript)
    owners = [b for b, ps in out["by_beat"].items() if ps]
    assert owners == ["b0"], out                 # start lives in b0
    assert not out["unplaced"]
    total = sum(len(ps) for ps in out["by_beat"].values())
    assert total == 1


def test_passage_in_no_beat_is_reported_unplaced_not_dropped():
    beats = _beats((0.0, 3.0), (3.0, 6.0))
    transcript = [{"id": "t0", "start_s": 8.0, "end_s": 9.5,
                   "text": "past every beat"}]
    out = assign_passages(beats, transcript)
    assert out["unplaced"] == transcript
    assert not any(out["by_beat"].values())


# ------------------------------------------------- variation rules --

def _sc(a_map, b=None, c=None, d=None):
    return {"A": a_map,
            "B": b or {}, "C": c or {}, "D": d or {},
            "hypotheses": {"B": "h", "C": "h", "D": "h"},
            "changed": {"B": "b0", "C": "b1", "D": "b2"},
            "factors": {"B": "hook", "C": "body", "D": "ending"},
            "metrics": {}}


def test_normalization_equivalent_copy_is_not_a_variation():
    """Punctuation/case churn is not a meaningful change."""
    beats = _beats((0.0, 3.0), (3.0, 6.0), (6.0, 9.0))
    sc = _sc({"b0": "watch this dog", "b1": "he runs fast",
              "b2": "good boy wins"},
             b={"b0": "Watch this dog!"},
             c={"b1": "a clearer line entirely"},
             d={"b2": "good boy wins watch"})
    problems = scripts.validate_variations(sc, beats)
    assert any("B" in p and "b0" in p for p in problems), problems


def test_missing_changed_copy_and_direction_are_reported():
    beats = _beats((0.0, 3.0), (3.0, 6.0), (6.0, 9.0))
    problems = scripts.validate_variations(_sc({}), beats)
    assert problems  # every variant reports its gap, never silent


# --------------------------------------------------- output profile --

def test_output_dims_are_a_frozen_declaration():
    assert scripts.output_dims("9:16", "720p") == (720, 1280)
    assert scripts.output_dims("9:16", "1080p") == (1080, 1920)
    assert scripts.output_dims("9:16", "180x320") == (180, 320)
    with pytest.raises(ContractError) as e:
        scripts.output_dims("9:16", "whatever")
    assert e.value.code == "unknown_resolution"
    with pytest.raises(ContractError) as e:
        scripts.output_dims("wide", "720p")
    assert e.value.code == "unknown_aspect"


# ---------------------------------------------- transcript quality --

def _transcript_doc(passages, language="en"):
    return {"format": "hypit.transcript@1", "language": language,
            "audio_seconds": 9.0, "passages": passages}


def _passage(text, s, e, words=None):
    if words is None:
        n = max(1, len(text.split()))
        step = (e - s) / n
        words = [{"text": w, "start_seconds": s + i * step,
                  "end_seconds": s + (i + 1) * step}
                 for i, w in enumerate(text.split() or ["x"])]
    return {"text": text, "start_seconds": s, "end_seconds": e,
            "words": words}


def test_transcript_repetition_loop_detected():
    doc = _transcript_doc(
        [_passage("and then it", i, i + 1) for i in range(6)])
    problems = transcript_problems(doc, 9.0, "en")
    assert any("loop" in p for p in problems)


def test_transcript_language_mismatch_detected():
    zh = _transcript_doc([_passage("这只狗接住了球", 0, 3)])
    assert any("CJK" in p or "language" in p
               for p in transcript_problems(zh, 9.0, "en"))
    en = _transcript_doc([_passage("the dog catches", 0, 3)])
    assert any("CJK" in p
               for p in transcript_problems(en, 9.0, "zh"))


def test_transcript_bad_timing_and_empty_detected():
    assert transcript_problems({"passages": []}, 9.0, "en")
    bad = _transcript_doc([
        {"text": "x", "start_seconds": "nope", "end_seconds": 2,
         "words": []}])
    assert transcript_problems(bad, 9.0, "en")
    late = _transcript_doc([_passage("past the end", 8.0, 40.0)])
    assert any("beyond" in p for p in transcript_problems(late, 9.0,
                                                          "en"))


# -------------------------------------------------------- frame clock --

def _probe_runner(streams, fmt=None, encode_ok=True):
    """Runner fake: ffprobe returns the given doc; ffmpeg 'succeeds' by
    emitting a stream stub only when probed back (normalize_section
    probes twice — source, then its own output)."""
    state = {"probed": []}

    def run(argv, timeout=60, cwd=None):
        if argv[0] == "ffprobe":
            path = argv[-1]
            state["probed"].append(path)
            if len(state["probed"]) == 1:
                doc = {"streams": streams, "format": fmt or {}}
            else:
                # The renderer's post-encode probe: report the frame
                # count the encode was asked to produce.
                doc = {"streams": [{"codec_type": "video",
                                    "nb_frames": str(
                                        state.get("frames", 90))}],
                       "format": {}}
            return type("R", (), {"returncode": 0,
                                  "stdout": json.dumps(doc),
                                  "stderr": ""})()
        if "-frames:v" in argv:
            state["frames"] = int(argv[argv.index("-frames:v") + 1])
        out = Path(argv[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return type("R", (), {"returncode": 0, "stdout": "",
                              "stderr": ""})()
    return run, state


def test_missing_stream_duration_falls_back_to_frame_count(tmp_path):
    """Matroska-style container: no stream duration, no format duration —
    nb_frames / fps is still verifiable evidence and must not read as a
    shortage."""
    r = FastPathRenderer()
    streams = [{"codec_type": "video", "width": 180, "height": 320,
                "nb_frames": "270", "avg_frame_rate": "30"}]
    runner, _ = _probe_runner(streams)
    r.runner = runner
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x")
    out, _ = r.normalize_section(str(src), 90, 30, str(tmp_path / "c"))
    assert Path(out).exists()


def test_no_clock_evidence_is_a_rejection_not_padding(tmp_path):
    streams = [{"codec_type": "video", "width": 180, "height": 320}]
    runner, _ = _probe_runner(streams)
    r = FastPathRenderer()
    r.runner = runner
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="no verifiable duration"):
        r.normalize_section(str(src), 90, 30, str(tmp_path / "c"))


def test_one_frame_shortage_permitted_larger_rejected(tmp_path):
    """A container duration landing exactly one frame short of the
    output clock is absorbed (the filter pads one frame); two frames
    short is a real shortage and must fail."""
    for shortfall, ok in ((1 / 30, True), (2 / 30, False)):
        streams = [{"codec_type": "video", "width": 180,
                    "height": 320, "duration": str(3.0 - shortfall)}]
        runner, _ = _probe_runner(streams)
        r = FastPathRenderer()
        r.runner = runner
        src = tmp_path / f"s{shortfall}.mp4"
        src.write_bytes(b"x")
        try:
            r.normalize_section(str(src), 90, 30, str(tmp_path / "c"))
            passed = True
        except RuntimeError as e:
            passed = False
            assert "short_footage" in str(e)
        assert passed == ok, f"shortfall {shortfall}"


def test_frame_rate_variants_checked_against_their_own_clock(tmp_path):
    """The one-frame allowance is defined in OUTPUT frames — 24fps and
    60fps sources get different tolerances."""
    for fps in (24, 60):
        frames = fps * 3
        # half a frame short of the required window: inside one frame
        streams = [{"codec_type": "video", "width": 180, "height": 320,
                    "duration": str(3.0 - 0.5 / fps)}]
        runner, _ = _probe_runner(streams)
        r = FastPathRenderer()
        r.runner = runner
        src = tmp_path / f"s{fps}.mp4"
        src.write_bytes(b"x")
        out, _ = r.normalize_section(str(src), frames, fps,
                                     str(tmp_path / f"c{fps}"))
        assert Path(out).exists()


# -------------------------------------------- provider diagnostics --

def _analyzer(tmp_path, response):
    from modules.factory.analysis.vertex import VertexAnalyzer
    from modules.factory.providers.vertex_auth import VertexAuth
    auth = VertexAuth(lambda: {
        "kind": "oauth", "access_token": "tok", "project": "p",
        "identity": "i", "scopes": ["cloud-platform"]}, "p")
    pricing = {"estimate_usd_micros": 1, "reserve_usd_micros": 2,
               "evidence": "fixture", "valid_until": "2999-01-01"}
    transport = lambda *a, **k: (200, {}, response)
    return VertexAnalyzer(tmp_path, None, auth, "acct", "proj",
                          "model", pricing, transport=transport)


def _candidate(text, finish="STOP"):
    return json.dumps({"candidates": [{
        "finishReason": finish,
        "content": {"parts": [{"text": text}]}}]}).encode()


def test_vertex_diagnostics_distinguish_failure_kinds(tmp_path):
    from modules.factory.testing.fakes import ProviderError
    cases = [
        (b"not json at all", "analysis_invalid_json"),
        (_candidate("")[0:0] or _candidate("unparsable"), 
         "analysis_invalid_json"),
        (_candidate('{"a": 1}', finish="SAFETY"), "analysis_blocked"),
        (_candidate('{"a": 1}', finish="MAX_TOKENS"),
         "analysis_incomplete"),
        (json.dumps({"candidates": []}).encode(),
         "analysis_missing_fields"),
        (json.dumps({"promptFeedback":
                     {"blockReason": "PROHIBITED_CONTENT"}}).encode(),
         "analysis_blocked"),
    ]
    for response, code in cases:
        ad = _analyzer(tmp_path, response)
        with pytest.raises(ProviderError) as e:
            ad.execute({"task": "translate", "model": "model",
                        "translation_input": {"passages": [{"index": 0,
                                                            "text": "x"}],
                                              "source_language": "en",
                                              "target_language": "es"}})
        assert e.value.code == code, (response, e.value.code)


def test_vertex_error_detail_is_bounded_and_redacted(tmp_path):
    from modules.factory.testing.fakes import ProviderError
    body = ("token=ya29.secretvalue " + "x" * 900).encode()
    transport = lambda *a, **k: (403, {}, body)
    from modules.factory.analysis.vertex import VertexAnalyzer
    from modules.factory.providers.vertex_auth import VertexAuth
    auth = VertexAuth(lambda: {"kind": "oauth", "access_token": "t",
                               "project": "p", "identity": "i",
                               "scopes": ["cloud-platform"]}, "p")
    ad = VertexAnalyzer(tmp_path, None, auth, "a", "p", "m",
                        {"estimate_usd_micros": 1,
                         "reserve_usd_micros": 1, "evidence": "f",
                         "valid_until": "2999-01-01"},
                        transport=transport)
    with pytest.raises(ProviderError) as e:
        ad.execute({"task": "translate", "model": "m",
                    "translation_input": {"passages": []}})
    assert e.value.code == "analysis_http_error"
    assert e.value.http_status == 403
    assert "secretvalue" not in (e.value.detail or "")
    assert len(e.value.detail or "") <= 400


def test_incomplete_translation_is_a_typed_failure(tmp_path):
    from modules.factory.testing.fakes import ProviderError
    ad = _analyzer(tmp_path, _candidate(
        '{"texts": {"0": "hola"}}'))       # index 1 missing
    with pytest.raises(ProviderError) as e:
        ad.execute({"task": "translate", "model": "model",
                    "translation_input": {
                        "passages": [{"index": 0, "text": "a"},
                                     {"index": 1, "text": "b"}],
                        "source_language": "en",
                        "target_language": "es"}})
    assert e.value.code == "malformed_analysis"


def test_analyze_media_rejects_short_coverage_beats(tmp_path):
    """The incident shape: valid JSON, beats covering 0.4s of a 37.6s
    probe — a billable, typed failure, not silent acceptance."""
    from modules.factory.testing.fakes import ProviderError
    payload = {"beats": [{"id": "b0", "role": "hook", "start_s": 0,
                          "end_s": 0.4, "confidence": "uncertain",
                          "visual_event": "x"}],
               "transcript": [], "music": {"role": "bed"},
               "uncertainty": []}
    ad = _analyzer(tmp_path, _candidate(json.dumps(payload)))
    src = tmp_path / "src.mp4"
    _moving_mp4(src, 4, size="180x320")
    import modules.factory.analysis.vertex as vx
    art = type("A", (), {"id": "art", "sha256": "s"})()

    class _Arts:
        def verified_path(self, aid): return src
        def path_for(self, aid): return str(src)
        class db:
            @staticmethod
            def uow():
                class U:
                    class artifacts:
                        @staticmethod
                        def get(aid): return {"kind": "video",
                                            "sha256": "s"}
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return U()
    ad.artifacts = _Arts()
    with pytest.raises(ProviderError) as e:
        ad.analyze_media(str(src), {"model": "model",
                                    "artifact_id": "art"})
    assert e.value.code == "invalid_analysis_timing"


# ---------------------------------------------------- worker ownership --

def test_second_worker_on_same_db_refuses(tmp_path):
    from modules.factory.bootstrap import bootstrap
    from modules.factory.services.worker import ApplicationWorker
    s = bootstrap(tmp_path / "one")
    w1 = ApplicationWorker(s)
    hold = w1._acquire_process_lock()   # the fd must stay open — the
    assert hold is not None            # lock lives as long as it does
    w2 = ApplicationWorker(s)
    with pytest.raises(ContractError) as e:
        w2._acquire_process_lock()
    assert e.value.code == "worker_already_running"
    # A worker for a DIFFERENT database is untouched.
    s2 = bootstrap(tmp_path / "two")
    w3 = ApplicationWorker(s2)
    assert w3._acquire_process_lock() is not None
