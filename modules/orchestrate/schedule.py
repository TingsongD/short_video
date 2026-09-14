"""M11 weekly schedule: crontab line for the weekly loop (Monday, off-peak
minute). `install` appends it to the user's crontab, guarded against dupes."""
import subprocess
from pathlib import Path

from modules.common.config import ROOT

RUN_SH = ROOT / "run.sh"
CRON_SPEC = "37 6 * * 1"  # Monday 06:37 local — off-peak minute
MARKER = "# shortform-ai: weekly radar->grill->formats"


def cron_line():
    return f"{CRON_SPEC} {RUN_SH} weekly >> {ROOT}/logs/weekly.log 2>&1 {MARKER}"


def installed(runner=subprocess.run):
    r = runner(["crontab", "-l"], capture_output=True, text=True)
    return r.returncode == 0 and MARKER in r.stdout


def install(runner=subprocess.run):
    """Append the weekly line to the user crontab; returns the line."""
    line = cron_line()
    r = runner(["crontab", "-l"], capture_output=True, text=True)
    existing = r.stdout if r.returncode == 0 else ""
    if MARKER in existing:
        return line
    new = existing.rstrip("\n") + ("\n" if existing.strip() else "") + line + "\n"
    p = runner(["crontab", "-"], input=new, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"crontab install failed: {p.stderr.strip()}")
    return line
