"""Shared config loading. Secret values are returned, never printed."""
import os
import re
import tomllib
from pathlib import Path

from dotenv.parser import parse_stream

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

# Accepted Google settings are kept separate; a key's name does not select an API.
GOOGLE_SETTINGS = {
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_TTS_VERTEX_API_KEY",
    "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS",
}


def load_toml(name):
    with open(CONFIG_DIR / name, "rb") as f:
        return tomllib.load(f)


def system():
    return load_toml("system.toml")


def niches():
    return load_toml("niches.toml")


def dotenv_secrets():
    """Read only this project's .env, without expansion, execution or logging."""
    path = ROOT / ".env"
    if not path.exists():
        return {}
    result = {}
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for binding in parse_stream(stream):
                if binding.error or (binding.key is not None and (
                    not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", binding.key)
                    or binding.value is None
                )):
                    # Parser originals can contain credentials. Report only location.
                    raise ValueError(
                        f"Invalid .env entry at line {binding.original.line}; expected KEY=VALUE"
                    )
                if binding.key is not None:
                    result[binding.key] = binding.value
    except UnicodeError:
        raise ValueError("The project .env must use UTF-8 text") from None
    return result


def secrets():
    """Nonempty environment > project .env > private TOML; never export values."""
    values = load_toml("secrets.toml")
    values.update({key: value for key, value in dotenv_secrets().items() if value != ""})
    for key in values.keys() | GOOGLE_SETTINGS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values
