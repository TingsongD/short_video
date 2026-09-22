"""Labeled signal fixtures for the flash-cut qualification matrix."""
from fractions import Fraction

import pytest

np = pytest.importorskip("numpy", reason="VALIDATION GAP: run isolated helper tests")


def _frames(count, *, changes=()):
    return [
        {
            "index": index,
            "source_time": str(Fraction(index, 30)),
            "change": 1 if index in changes else 0,
            "novelty": 0,
        }
        for index in range(count)
    ]


def test_labeled_visual_matrix_preserves_continuity_flash_and_callback():
    from modules.factory.analysis.event_fusion import (
        fuse_events, visual_recurrences,
    )

    continuous = fuse_events(_frames(90), [], duration="3")
    assert not [candidate for candidate in continuous["candidates"]
                if candidate["kind"] == "visual_change_candidate"]
    assert {0, 89}.issubset(continuous["selected_frame_indices"])

    frames = _frames(90, changes=(30, 32))
    vectors = np.zeros((90, 512), dtype=np.float32)
    vectors[:30, 0] = 1
    vectors[30:32, 1] = 1
    vectors[32:, 0] = 1
    recurrences = visual_recurrences(frames, vectors)
    result = fuse_events(frames, [], duration="3", recurrences=recurrences)
    selected = set(result["selected_frame_indices"])
    assert {30, 31}.issubset(selected)  # the complete two-frame flash
    assert any(item["frame_index"] == 32
               and item["claim"] == "visual_resemblance_only"
               for item in recurrences)
    assert any(candidate["kind"] == "recurrence_candidate"
               and candidate["mandatory"] is True
               for candidate in result["candidates"])


def test_labeled_audio_matrix_distinguishes_silence_weak_and_clear_rhythm():
    from modules.factory.media.audio_events import analyze_audio

    silence = analyze_audio(np.zeros((48000 * 2, 2), dtype=np.float32))
    assert silence["status"] == "measured_no_events"
    assert silence["rhythm_status"] == "rhythm_unreliable"

    weak = np.zeros((48000 * 6, 1), dtype=np.float32)
    weak[48000:48480, 0] = .8 * np.sin(
        np.arange(480) * 2 * np.pi * 120 / 48000
    )
    weak_result = analyze_audio(weak)
    assert weak_result["rhythm_status"] == "rhythm_unreliable"
    assert not any(event["kind"] == "rhythmic_beat_candidate"
                   for event in weak_result["events"])

    clear = np.zeros((48000 * 6, 1), dtype=np.float32)
    pulse = .8 * np.sin(np.arange(960) * 2 * np.pi * 120 / 48000)
    for point in np.arange(.5, 5.6, .5):
        start = round(float(point) * 48000)
        clear[start:start + len(pulse), 0] = pulse
    clear_result = analyze_audio(clear)
    assert clear_result["rhythm_status"] == "supported_candidates"
    beats = [event for event in clear_result["events"]
             if event["kind"] == "rhythmic_beat_candidate"]
    assert len(beats) >= 8
    assert all(abs(event["period_s"] - .5) <= .01 for event in beats)


def test_audiovisual_disagreement_preserves_both_measurements_without_claim():
    from modules.factory.analysis.event_fusion import fuse_events

    frames = _frames(90, changes=(30,))
    audio = [{
        "id": "onset:72000", "kind": "onset_candidate",
        "sample": 72000, "sample_rate": 48000,
        "support": ["spectral_change"],
    }]
    result = fuse_events(frames, audio, duration="3")
    by_kind = {candidate["kind"]: candidate
               for candidate in result["candidates"]
               if candidate["kind"] in (
                   "visual_change_candidate", "onset_candidate")}
    assert by_kind["visual_change_candidate"]["source_time"] == "1"
    assert by_kind["visual_change_candidate"]["mandatory"] is True
    assert by_kind["onset_candidate"]["source_time"] == "3/2"
    assert by_kind["onset_candidate"]["mandatory"] is False
    assert not any(candidate["kind"] in ("scene_change", "beat_drop")
                   for candidate in result["candidates"])
