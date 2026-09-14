"""G0: required workspace structure exists (BUILD_PLAN.md M0)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DIRS = [
    "data/radar",
    "data/grill",
    "data/formats",
    "data/hooks",
    "data/production",
    "data/published",
    "data/analytics",
    "data/costs",
    "modules",
    "schemas",
    "tests/fixtures",
    "vendor",
    "config",
    "logs",
    "docs",
]

REQUIRED_FILES = [
    "BUILD_PLAN.md",
    "GOAL.md",
    "AGENTS.md",
    "Makefile",
    "config/system.toml",
    "config/niches.toml",
    "config/secrets.toml",
    "config/secrets.example.toml",
    "docs/gates.md",
    "docs/vendor-pins.md",
    "PROGRESS.md",
]


def test_required_dirs_exist():
    missing = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    assert not missing, f"missing directories: {missing}"


def test_required_files_exist():
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    assert not missing, f"missing files: {missing}"
