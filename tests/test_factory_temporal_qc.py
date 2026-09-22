"""Targeted final-timeline checks for the future flash-cut profile.

These checks prove decoded frame timing and planned caption/event occupancy.
They deliberately do not claim semantic footage identity, OCR, or lip sync.
"""
import json
from types import SimpleNamespace

from modules.factory.quality import TechnicalQC


def _result(*, stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr,
                           returncode=returncode)


class TemporalRunner:
    def __init__(self, *, pts=None, hashes=None):
        self.pts = pts or ["0", "0.033333", "0.066667", "0.100000",
                           "0.133333", "0.166667"]
        self.hashes = hashes or ["a", "a", "b", "b", "c", "c"]

    def __call__(self, argv, timeout=60):
        if argv[0] == "ffprobe" and "-show_frames" in argv:
            return _result(stdout=json.dumps({"frames": [
                {"best_effort_timestamp_time": value}
                for value in self.pts
            ]}))
        if argv[0] == "ffprobe":
            return _result(stdout=json.dumps({
                "streams": [{
                    "codec_type": "video", "avg_frame_rate": "30/1",
                    "nb_frames": "6", "duration": "0.2",
                    "width": 180, "height": 320,
                }],
                "format": {"duration": "0.2"},
            }))
        if "framemd5" in argv:
            rows = "\n".join(
                f"0, {index}, {index}, 1, 1, {digest}"
                for index, digest in enumerate(self.hashes)
            )
            return _result(stdout=rows + "\n")
        # Full decode and black/freeze detectors are both clean.
        return _result()


def _expected():
    return {
        "frames": 6, "fps": 30, "fps_num": 30, "fps_den": 1,
        "width": 180, "height": 320, "has_audio": False,
        "temporal": {
            "version": "flashcut_temporal_qc.v1",
            "caption_alignment": "final_speech_schedule.v1",
            "brief_event_max_frames": 6,
            "captions": [{
                "id": "caption-0", "text": "hello world",
                "start_frame": 1, "end_frame": 3,
            }],
            "passages": [{
                "id": "p0", "text": "hello world",
                "in_frame": 0, "out_frame": 6,
                "words": [
                    {"text": "hello", "start_frame": 1,
                     "end_frame": 2},
                    {"text": "world", "start_frame": 2,
                     "end_frame": 3},
                ],
                "phrases": [[0, 1]],
            }],
            "brief_events": [{
                "id": "flash", "kind": "cut", "required": True,
                "start_frame": 2, "end_frame": 4,
            }],
        },
    }


def test_temporal_qc_covers_all_pts_final_speech_and_brief_event():
    report = TechnicalQC(runner=TemporalRunner()).inspect("final.mp4",
                                                          _expected())
    assert report["ok"], report
    coverage = report["temporal_coverage"]
    assert coverage["video_pts"]["frames"] == 6
    assert coverage["captions"] == {
        "count": 1,
        "method": "schedule_vs_final_speech_alignment",
        "pixel_ocr": False,
    }
    assert coverage["brief_events"]["inspected"] == ["flash"]
    assert coverage["brief_events"]["method"] == \
        "decoded_frame_boundary_presence"
    assert coverage["brief_events"]["semantic_identity"] is False
    assert coverage["lip_sync"] == "not_verified"


def test_temporal_qc_rejects_output_pts_discontinuity():
    pts = ["0", "0.033333", "0.066667", "0.200000", "0.233333",
           "0.266667"]
    report = TechnicalQC(runner=TemporalRunner(pts=pts)).inspect(
        "final.mp4", _expected())
    assert not report["ok"]
    assert "video_pts_discontinuity" in {
        finding["code"] for finding in report["findings"]
    }


def test_temporal_qc_rejects_caption_drift_from_final_alignment():
    expected = _expected()
    expected["temporal"]["captions"][0]["end_frame"] = 4
    report = TechnicalQC(runner=TemporalRunner()).inspect("final.mp4",
                                                          expected)
    assert not report["ok"]
    assert "caption_alignment_drift" in {
        finding["code"] for finding in report["findings"]
    }


def test_temporal_qc_rejects_collapsed_brief_event():
    report = TechnicalQC(
        runner=TemporalRunner(hashes=["a"] * 6)
    ).inspect("final.mp4", _expected())
    assert not report["ok"]
    assert "brief_event_not_visible" in {
        finding["code"] for finding in report["findings"]
    }
