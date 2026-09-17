"""Configuration (F30): nonempty environment variables > .env >
private TOML. Safe settings separate from credential references —
secret values never reach frontend build variables.
"""
import os
import tomllib
from pathlib import Path

SAFE_KEYS = {"API_PORT", "WORKER_PORT", "DATA_ROOT", "DRIVE_FOLDER_ID",
             "LOG_LEVEL", "MEDIA_MAX_MB"}
CREDENTIAL_REFS = {"CANVAS_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS",
                   "VERTEX_PROJECT", "UPLOAD_POST_KEY"}


def _env_file(path):
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _toml(path):
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def load_config(root, env=None):
    """→ {values, sources, credential_refs_present, missing_safe}.
    env vars win only when nonempty — an empty string never shadows
    a configured value."""
    root = Path(root)
    env = os.environ if env is None else env
    flat_toml = {k: str(v) for k, v in _toml(root / "config"
                                              / "secrets.toml").items()
                 if isinstance(v, (str, int))}
    dotenv = _env_file(root / ".env")
    keys = set(flat_toml) | set(dotenv) | set(env) | SAFE_KEYS
    values, sources = {}, {}
    for k in sorted(keys):
        if k in env and env[k]:
            values[k], sources[k] = env[k], "env"
        elif k in dotenv and dotenv[k]:
            values[k], sources[k] = dotenv[k], "env_file"
        elif k in flat_toml:
            values[k], sources[k] = flat_toml[k], "toml"
    safe = {k: v for k, v in values.items() if k in SAFE_KEYS}
    creds = {k: ("set" if values.get(k) else "absent")
             for k in CREDENTIAL_REFS}
    return {"values": safe, "sources": sources,
            "credential_refs_present": creds,
            "missing_safe": sorted(SAFE_KEYS - set(safe))}
