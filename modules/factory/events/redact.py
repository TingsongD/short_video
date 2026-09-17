"""Log/evidence redaction (F08 checklist 4). Logs carry artifact and
receipt references — never credential material, confirmation tokens,
OAuth codes or signed URLs."""
import re

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),                    # Google API key
    re.compile(r"sk[-_][0-9A-Za-z_-]{20,}"),                 # API keys
    re.compile(r"(?<![A-Za-z0-9_/])4/[0-9A-Za-z_-]{20,}"),                    # OAuth code
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

SECRET_KEYS = {"authorization", "cookie", "setcookie", "apikey", "key",
               "accesstoken", "refreshtoken", "idtoken", "token",
               "confirmationtoken", "confirmtoken", "oauthcode",
               "verificationcode", "clientsecret", "password", "secret"}


def _secret_field(key, value, context=None):
    name = re.sub(r"[^a-z]", "", str(key).lower())
    if name=="key" and isinstance(value,str) and context:
        if value in ("A","B","C","D") and {"factor","segments"}<=context.keys():return False
        if value.isdigit() and {"request","price"}<=context.keys():return False
    # Domain authorization metadata is public; HTTP authorization strings
    # are credentials. Recurse into metadata to remove nested credentials.
    return name in SECRET_KEYS and not (name == "authorization" and isinstance(value, dict))


def redact(value):
    if isinstance(value, str):
        for pat in SECRET_PATTERNS:
            value = pat.sub("[redacted]", value)
        return value
    if isinstance(value, dict):
        return {k: ("[redacted]" if _secret_field(k, v, value) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
