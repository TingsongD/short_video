"""B2 regression: AVD win/loss verdicts must use the REAL video length,
not a phantom default. A 30s watch is a win on a 30s video but a loss
on a 50s video (0.7 * 50 = 35s required)."""
from modules.analytics.verdict import verdict

CFG = {"win_views_multiplier": 2.0, "win_avd_ratio": 0.7}
WINDOW = {"views": 5000, "avg_view_duration_s": 30.0}  # views >> 2x median


def test_same_avd_wins_on_30s_video():
    assert verdict(WINDOW, 30, 1000, CFG) == "win"


def test_same_avd_loses_on_50s_video():
    assert verdict(WINDOW, 50, 1000, CFG) == "loss"


def test_avd_exactly_at_ratio_wins():
    assert verdict({"views": 5000, "avg_view_duration_s": 35.0}, 50, 1000, CFG) == "win"


def test_missing_length_cannot_win():
    # no length recorded -> avd_win is False -> loss, never a silent win
    assert verdict(WINDOW, None, 1000, CFG) == "loss"
    assert verdict(WINDOW, 0, 1000, CFG) == "loss"
