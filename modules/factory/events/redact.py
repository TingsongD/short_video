"""Log/evidence redaction (F08 checklist 4). Logs carry artifact and
receipt references — never credential material, confirmation tokens,
OAuth codes or signed URLs."""
import re

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),                    # Google API key
    re.compile(r"sk-[0-9A-Za-z]{20,}"),                       # OpenAI-style
    re.compile(r"ya29\.[0-9A-Za-z_-]{10,}"),                  # Google OAuth token
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{10,}", re.I),
    re.compile(r"access_token[\"']?\s*[:=]\s*[\"'][^\"'\s]+", re.I),
    re.compile(r"refresh_token[\"']?\s*[:=]\s*[\"'][^\"'\s]+", re.I),
    re.compile(r"(code|confirm(?:ation)?_token)[\"']?\s*[:=]\s*[\"'][^\"'\s]+",
               re.I),
    re.compile(r"[?&](sig|signature|X-Goog-Signature|token|key)="
               r"[0-9A-Za-z%._~+/=-]{8,}", re.I),             # signed URL params
    re.compile(r"[?&]Expires=[0-9]+", re.I),
]


def redact(value):
    if isinstance(value, str):
        for pat in SECRET_PATTERNS:
            value = pat.sub("[redacted]", value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
