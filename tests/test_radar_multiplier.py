"""M1: median & multiplier math (BUILD_PLAN test_multiplier)."""
from modules.radar.metrics import channel_median, multiplier, subs_ratio


def test_median_odd_count():
    assert channel_median([900, 1000, 1100]) == 1000.0


def test_median_even_count():
    assert channel_median([900, 950, 1050, 1100]) == 1000.0


def test_median_empty_and_zero_views():
    assert channel_median([]) == 0.0
    assert channel_median([0, 0, 0]) == 0.0


def test_multiplier_normal():
    assert multiplier(6200, 1000) == 6.2


def test_multiplier_zero_baseline_no_crash():
    assert multiplier(500, 0) == 0.0


def test_multiplier_zero_views():
    assert multiplier(0, 1000) == 0.0


def test_subs_ratio():
    assert subs_ratio(6200, 2000) == 3.1
    assert subs_ratio(100, 0) == 0.0
