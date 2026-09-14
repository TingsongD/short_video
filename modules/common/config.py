"""Shared config loading. Secret values are returned, never printed."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def load_toml(name):
    with open(CONFIG_DIR / name, "rb") as f:
        return tomllib.load(f)


def system():
    return load_toml("system.toml")


def niches():
    return load_toml("niches.toml")


def secrets():
    return load_toml("secrets.toml")
