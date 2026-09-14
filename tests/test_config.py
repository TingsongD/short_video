"""G0: config files parse and thresholds are sane (BUILD_PLAN.md M0)."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    with open(ROOT / "config" / name, "rb") as f:
        return tomllib.load(f)


def test_system_toml_parses():
    cfg = _load("system.toml")
    for section in ("radar", "grill", "formats", "voice", "assembly", "publish", "readback", "costs"):
        assert section in cfg, f"missing section [{section}]"


def test_radar_thresholds_sane():
    radar = _load("system.toml")["radar"]
    assert radar["breakout_multiplier"] >= 2.0
    assert radar["breakout_subs_ratio"] >= 1.0
    assert 1 <= radar["max_video_age_days"] <= 60
    assert radar["cluster_min_channels"] >= 2
    assert 0 < radar["daily_quota_budget"] <= 10000


def test_grill_thresholds_sane():
    grill = _load("system.toml")["grill"]
    assert 1.0 <= grill["pass_hook_score"] <= 10.0
    assert 1.0 <= grill["pass_virality_score"] <= 10.0
    assert grill["ideas_per_cluster"] >= 1


def test_voice_duration_window_valid():
    voice = _load("system.toml")["voice"]
    assert 0 < voice["min_duration_s"] < voice["max_duration_s"] <= 180


def test_assembly_is_shorts_shape():
    assembly = _load("system.toml")["assembly"]
    assert assembly["video_aspect"] == "9:16"
    assert assembly["resolution"] == "1080x1920"


def test_readback_windows_ordered():
    hours = _load("system.toml")["readback"]["windows_hours"]
    assert hours == sorted(hours) and len(hours) == 3


def test_niches_toml_has_seed_niches():
    niches = _load("niches.toml")["niche"]
    assert len(niches) >= 3, "need at least 3 seed niches for testing"
    for n in niches:
        assert n["name"] and n["keywords"], f"niche missing name/keywords: {n}"
        assert isinstance(n["seed_channels"], list)
