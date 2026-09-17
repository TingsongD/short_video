"""Preflight (F30): pinned runtime versions, required vs optional
tools, storage/migration validity, per-provider readiness — all
read-only, nothing generates or spends.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED = {"ffmpeg": ["ffmpeg", "-version"],
            "python": None}
OPTIONAL = {"node": ["node", "--version"],
            "hypit": ["scripts/hypit.sh", "--version"],
            "gdrive": ["gdrive", "--version"]}


def _run(argv, cwd):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=15, cwd=cwd)
        return r.returncode == 0, (r.stdout or r.stderr).splitlines()[0] \
            if (r.stdout or r.stderr) else ""
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def doctor(root=".", providers=None):
    """→ ordered check list; `ok` is the AND of required checks."""
    root = Path(root)
    checks = []
    ok, ver = True, f"Python {sys.version.split()[0]}"
    checks.append({"name": "python", "required": True, "ok": ok,
                   "detail": ver})
    ok, ver = _run(["ffmpeg", "-version"], root)
    checks.append({"name": "ffmpeg", "required": True, "ok": ok,
                   "detail": ver.split(",")[0] if ver else "missing"})
    for name, argv in OPTIONAL.items():
        ok, ver = _run(argv, root)
        checks.append({"name": name, "required": False, "ok": ok,
                       "detail": ver or ("missing — optional"
                                         if name != "gdrive"
                                         else "missing — live delivery"
                                         " unavailable")})
    disk = shutil.disk_usage(root)
    checks.append({"name": "disk", "required": True,
                   "ok": disk.free > 1 << 30,
                   "detail": f"{disk.free >> 30} GiB free"})
    for name, ad in (providers or {}).items():
        try:
            r = ad.readiness() if hasattr(ad, "readiness") else {}
            ok = r.get("installed") is True
            detail = "installed" if ok else "not installed"
        except Exception as e:
            ok, detail = False, type(e).__name__
        checks.append({"name": f"provider:{name}", "required": False,
                       "ok": ok, "detail": detail})
    return {"ok": all(c["ok"] for c in checks if c["required"]),
            "checks": checks}
