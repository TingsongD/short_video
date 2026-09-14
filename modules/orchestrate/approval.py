"""M11 approval gate: no paid call executes without an approval token.

Approval sources, in order:
1. PIPELINE_APPROVE=1 env (non-interactive / CI)
2. data/approvals/<scope>.json token (written by `run.sh approve <scope>`)
3. interactive y/N prompt when stdin is a TTY
Otherwise ApprovalDenied is raised BEFORE the paid callable runs.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.common.config import DATA_DIR

APPROVALS_DIR = DATA_DIR / "approvals"


class ApprovalDenied(RuntimeError):
    pass


def grant(scope, directory=None, ttl_hours=24, now=None):
    d = Path(directory or APPROVALS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    token = {
        "scope": scope,
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
    }
    p = d / f"{scope}.json"
    p.write_text(json.dumps(token, indent=2) + "\n", encoding="utf-8")
    return p


def is_approved(scope, directory=None, now=None):
    if os.environ.get("PIPELINE_APPROVE") == "1":
        return True
    p = Path(directory or APPROVALS_DIR) / f"{scope}.json"
    if not p.exists():
        return False
    exp = json.loads(p.read_text()).get("expires_at")
    return not exp or datetime.fromisoformat(exp) > (
        now or datetime.now(timezone.utc))


def require(scope, detail="", directory=None, prompter=None, now=None):
    if is_approved(scope, directory, now):
        return
    ask = prompter or (input if sys.stdin.isatty() else None)
    if ask:
        ans = ask(f"Approve spend [{scope}] {detail}? [y/N] ")
        if ans.strip().lower() in {"y", "yes"}:
            grant(scope, directory, now=now)
            return
    raise ApprovalDenied(
        f"scope '{scope}' not approved — run `run.sh approve {scope}` "
        f"or set PIPELINE_APPROVE=1")
