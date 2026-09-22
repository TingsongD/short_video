"""Offline oversized-final regression at the provider quote boundary."""
from test_factory_analysis_timing_recovery import analyzer
import hashlib
import subprocess

import pytest

from modules.factory.analysis.review_media import prepare, _validate
from modules.factory.domain.errors import ContractError
from modules.factory.media.probe import probe


def test_final_review_quotes_bounded_derivative_not_oversized_original(tmp_path, monkeypatch):
    ad, request, calls = analyzer(tmp_path, monkeypatch, {"verdict": "pass"})
    request["task"] = "review_final"
    ad.maximum = 10
    prepared = []
    def review_input(request):
        prepared.append(request["artifact_sha256"])
        return tmp_path / "proxy.mp4", {"source_sha256": request["artifact_sha256"]}
    monkeypatch.setattr(ad, "_review_input", review_input, raising=False)
    quote = ad.price(request)
    assert quote["reserve_amount"] == 250000
    assert prepared == [request["artifact_sha256"]]
    assert calls == []


def test_real_review_copy_preserves_final_and_uses_verified_cache(tmp_path, monkeypatch):
    original = tmp_path / "final.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10",
        "-c:a", "aac", str(original)], check=True, capture_output=True, timeout=30)
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    limit = 600000
    assert original.stat().st_size > limit
    copy, evidence = prepare(original, sha, tmp_path / "cache", limit)
    assert copy != original and copy.stat().st_size <= limit
    assert evidence["derived"] and evidence["source_sha256"] == sha
    assert hashlib.sha256(original.read_bytes()).hexdigest() == sha
    _validate(probe(original), probe(copy), limit)
    # A second call must verify and reuse, not encode again.
    real_run = subprocess.run
    def no_encoder(args, **kwargs):
        assert args[0] != "ffmpeg"
        return real_run(args, **kwargs)
    monkeypatch.setattr(subprocess, "run", no_encoder)
    assert prepare(original, sha, tmp_path / "cache", limit) == (copy, evidence)


def test_changed_original_rejected_before_encode(tmp_path):
    original = tmp_path / "final.mp4"
    original.write_bytes(b"changed")
    with pytest.raises(ContractError, match="analysis_media_changed"):
        prepare(original, "0" * 64, tmp_path / "cache", 10)


def test_small_original_is_not_reencoded(tmp_path):
    original = tmp_path / "final.mp4"
    original.write_bytes(b"small")
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    path, evidence = prepare(original, sha, tmp_path / "cache", 10)
    assert path == original and evidence["derived"] is False


def test_review_note_string_remains_complete_sentence(tmp_path, monkeypatch):
    ad, request, _ = analyzer(tmp_path, monkeypatch,
                             {"verdict": "pass", "notes": "The video matches its script."})
    request["task"] = "review_final"
    result, _, _ = ad.execute(request)
    assert result["review"]["notes"] == ["The video matches its script."]


def test_final_review_distinguishes_source_overlays_from_replacement_captions(tmp_path, monkeypatch):
    ad, request, calls = analyzer(tmp_path, monkeypatch, {'verdict':'pass','notes':[]})
    request.update(task='review_final',expected={'policy':'visual.v2',
        'scenes':[{'source_overlays':['给妈买包'],'environmental_text':['BED']}],
        'segments':[{'copy':'Go fund Mom\'s bags!'}]})
    ad.execute(request)
    prompt=calls[0]['contents'][0]['parts'][-1]['text']
    assert 'source_overlays are reference-only' in prompt
    assert 'Their absence is not a defect' in prompt
    assert 'final script and replacement narration' in prompt
    assert 'environmental_text' in prompt
    assert request['expected']['scenes'][0]['source_overlays']==['给妈买包']


@pytest.mark.parametrize('issues,verdict', [([], 'uncertain'),
    ([{'start_s':0,'end_s':8,'observation':'Different shirt'}], 'uncertain'),
    ([{'start_s':1,'end_s':2,'observation':'The recurring maker changes face within the same scene'}], 'fail')])
def test_scene_aware_failure_requires_timestamped_evidence(tmp_path, monkeypatch, issues, verdict):
    ad, request, calls = analyzer(tmp_path,monkeypatch,{'verdict':'fail','issues':issues,'notes':[]})
    request.update(task='review_final',expected={'policy':'visual.v2','scenes':[{'allowed_transition':'new presenter'}]})
    result,_,_ = ad.execute(request)
    assert result['review']['verdict'] == verdict
    prompt = calls[0]['contents'][0]['parts'][-1]['text']
    assert 'Use only supplied footage' in prompt
    assert 'new presenter' in prompt


@pytest.mark.parametrize("field,value", [("duration_s", 1), ("byte_count", 2000000)])
def test_invalid_copy_never_accepted(field, value):
    from fractions import Fraction
    from modules.factory.media.probe import Probe, StreamInfo
    import copy
    source = Probe(duration_s=4, byte_count=100,
                   streams=[StreamInfo(codec_type="video", width=720, height=1280,
                                       avg_frame_rate=Fraction(30), nb_frames=120)])
    derived = copy.deepcopy(source)
    setattr(derived, field, value)
    with pytest.raises(ContractError):
        _validate(source, derived, 1000)
