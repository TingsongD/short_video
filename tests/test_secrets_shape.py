"""G0: secrets file shape + gitignore coverage. NEVER reads or prints values."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_KEYS = [
    "YOUTUBE_API_KEY",
    "PEXELS_API_KEY",
    "ELEVENLABS_API_KEY",
    "LLM_PROVIDER",
    "LLM_API_KEY",
]


def test_secrets_file_has_required_keys():
    with open(ROOT / "config" / "secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
    missing = [k for k in REQUIRED_KEYS if k not in secrets]
    assert not missing, f"secrets.toml missing keys: {missing}"


def test_secrets_toml_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text()
    assert "config/secrets.toml" in gitignore, "secrets.toml must be gitignored"


def test_example_and_real_secrets_have_same_keys():
    def keys(name):
        with open(ROOT / "config" / name, "rb") as f:
            return set(tomllib.load(f).keys())

    assert keys("secrets.toml") == keys("secrets.example.toml"), (
        "secrets.toml and secrets.example.toml key sets drifted"
    )


def test_no_key_shaped_strings_in_tracked_files():
    """Sweep tracked text files for API-key-shaped strings (values must live only in gitignored secrets.toml)."""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    pattern = re.compile(r"(AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{20,})")
    offenders = []
    for rel in out:
        p = ROOT / rel
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
        if pattern.search(text):
            offenders.append(rel)
    assert not offenders, f"key-shaped strings found in tracked files: {offenders}"
