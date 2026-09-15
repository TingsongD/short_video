"""M11 pipeline runner: stages execute strictly in order; the first failure
stops the run and is recorded to logs/runs/<ts>-<cmd>.json."""
import json
from datetime import datetime, timezone
from pathlib import Path

from modules.common.config import ROOT

LOGS_DIR = ROOT / "logs" / "runs"


class ReviewRequired(RuntimeError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


def run_stages(cmd, stages, log_dir=None, now=None):
    """stages: ordered list of (name, callable). Returns the run record."""
    record = {
        "cmd": cmd,
        "started_at": (now or datetime.now(timezone.utc)).isoformat(),
        "stages": [],
        "status": "ok",
    }
    import time
    for name, fn in stages:
        t0 = time.monotonic()
        try:
            fn()
            record["stages"].append({
                "name": name, "status": "ok",
                "duration_s": round(time.monotonic() - t0, 3)})
        except ReviewRequired as e:
            record["stages"].append({"name": name, "status": "needs_review",
                                     "duration_s": round(time.monotonic() - t0, 3),
                                     "error": str(e), "details": e.details})
            record["status"] = "needs_review"
            record["stopped_at"] = name
            break
        except Exception as e:
            record["stages"].append({
                "name": name, "status": "failed",
                "duration_s": round(time.monotonic() - t0, 3),
                "error": f"{type(e).__name__}: {e}",
            })
            record["status"] = "failed"
            record["failed_at"] = name
            break
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    d = Path(log_dir or LOGS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    stamp = record["started_at"].replace(":", "").replace("+", "Z")[:19]
    p = d / f"{stamp}-{cmd}.json"
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    record["log_path"] = str(p)
    return record
