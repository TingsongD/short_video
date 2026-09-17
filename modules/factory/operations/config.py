"""Configuration (F30): nonempty environment variables > .env >
private TOML. Safe settings separate from credential references —
secret values never reach frontend build variables.
"""
import os
import tomllib
from pathlib import Path

SAFE_KEYS = {"API_PORT", "DATA_ROOT", "FACTORY_EXECUTION_MODE", "DRIVE_FOLDER_ID",
             "LOG_LEVEL", "MEDIA_MAX_MB"}
CREDENTIAL_REFS = {"CANVAS_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS",
                   "VERTEX_PROJECT", "UPLOAD_POST_KEY", "UPLOAD_POST_API_KEY", "ELEVENLABS_API_KEY",
                   "SHOPIFY_ADMIN_ACCESS_TOKEN", "VIRAL_OUTLIERS_API_KEY", "GEMINI_TTS_VERTEX_API_KEY", "GOOGLE_CLOUD_PROJECT"}


def _env_file(path):
    out = {}
    if not path.exists():
        return out
    from dotenv.parser import parse_stream
    from ..domain.errors import ContractError
    with path.open(encoding="utf-8-sig") as stream:
        for binding in parse_stream(stream):
            if binding.error:
                raise ContractError("invalid_dotenv","line",str(binding.original.line))
            if binding.key and binding.value is not None:
                out[binding.key] = binding.value
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
    def flatten(tree,prefix=""):
        result={}
        for key,value in tree.items():
            name=(prefix+"_"+key).strip("_").upper()
            if isinstance(value,dict): result.update(flatten(value,name))
            elif isinstance(value,(str,int)): result[name]=str(value)
        return result
    flat_toml={**flatten(_toml(root/"config"/"factory.toml")), **flatten(_toml(root/"config"/"secrets.toml"))}
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
    return {"values": safe, "sources": {k:v for k,v in sources.items() if k in SAFE_KEYS | CREDENTIAL_REFS},
            "credential_refs_present": creds,
            "missing_safe": sorted(SAFE_KEYS - set(safe))}
