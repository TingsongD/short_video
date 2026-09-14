"""M3: promote/retire at exact thresholds (test_promote)."""
import copy
import json
from pathlib import Path

from modules.formats.promote import apply_readback, evaluate, update_entry

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
CFG = {"promote_min_videos": 3, "promote_min_multiplier": 1.5,
       "retire_consecutive_losses": 3}


def _entry():
    f = copy.deepcopy(
        json.loads((FIXTURES / "format_library.sample.json").read_text())
    )["formats"][0]
    return f


def _rb(verdict, views=3000, baseline=1000):
    return {
        "video_id": "v-x", "verdict": verdict,
        "windows": {"48h": {"pulled_at": "2026-09-16T00:00:00Z", "views": views}},
        "baseline_median_views": baseline, "format_promotion": "none",
    }


def test_three_wins_at_15x_promotes():
    e = _entry()
    for _ in range(3):
        e, _ = update_entry(e, _rb("win", views=1500, baseline=1000), CFG)
    assert e["status"] == "proven"
    assert e["our_stats"]["videos"] == 3
    assert e["our_stats"]["avg_multiplier"] == 1.5


def test_below_min_videos_stays_candidate():
    e = _entry()
    for _ in range(2):
        update_entry(e, _rb("win"), CFG)
    assert e["status"] == "candidate"


def test_below_multiplier_threshold_stays_candidate():
    e = _entry()
    for _ in range(3):
        update_entry(e, _rb("win", views=1400, baseline=1000), CFG)
    assert e["status"] == "candidate"  # avg 1.4 < 1.5


def test_three_consecutive_losses_retires():
    e = _entry()
    e["status"] = "proven"
    for _ in range(3):
        e, _ = update_entry(e, _rb("loss", views=200), CFG)
    assert e["status"] == "retired"


def test_win_resets_loss_streak():
    e = _entry()
    update_entry(e, _rb("loss", views=100), CFG)
    update_entry(e, _rb("loss", views=100), CFG)
    update_entry(e, _rb("win", views=5000), CFG)
    assert e["our_stats"]["consecutive_losses"] == 0
    assert e["status"] != "retired"
    update_entry(e, _rb("loss", views=100), CFG)
    assert e["status"] != "retired"  # streak restarted at 1


def test_pending_verdict_counts_video_not_streak():
    e = _entry()
    update_entry(e, _rb("pending"), CFG)
    assert e["our_stats"]["videos"] == 1
    assert e["our_stats"]["consecutive_losses"] == 0
