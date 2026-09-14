"""M11 cost ledger: every paid call is appended to data/costs/ledger.json;
the configured weekly cap is a hard stop enforced BEFORE the call runs."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.common.config import DATA_DIR

LEDGER_PATH = DATA_DIR / "costs" / "ledger.json"


class BudgetExceeded(RuntimeError):
    """Raised when a paid call would exceed the configured weekly cap."""


def week_start(now):
    d = now.astimezone(timezone.utc)
    return (d - timedelta(days=d.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)


class CostLedger:
    def __init__(self, path=None, weekly_cap=None):
        self.path = Path(path or LEDGER_PATH)
        self.weekly_cap = weekly_cap
        self.entries = self._load()

    def _load(self):
        if self.path.exists():
            return json.loads(self.path.read_text()).get("entries", [])
        return []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"entries": self.entries}, indent=2) + "\n",
            encoding="utf-8")

    def record(self, service, cost_usd, *, units=None, unit_type=None,
               video_id=None, note=None, approved=True, now=None):
        entry = {
            "ts": (now or datetime.now(timezone.utc)).isoformat(),
            "service": service,
            "cost_usd": round(float(cost_usd), 6),
            "approved": bool(approved),
        }
        if units is not None:
            entry["units"] = units
        if unit_type:
            entry["unit_type"] = unit_type
        if video_id:
            entry["video_id"] = video_id
        if note:
            entry["note"] = note
        self.entries.append(entry)
        self._save()
        return entry

    def spent_since(self, since):
        return sum(
            e["cost_usd"] for e in self.entries
            if datetime.fromisoformat(e["ts"]) >= since)

    def spent_week(self, now=None):
        return self.spent_since(week_start(now or datetime.now(timezone.utc)))

    def authorize(self, service, est_cost_usd, now=None):
        """Hard stop: raise before a paid call if it would breach the cap."""
        if self.weekly_cap is None:
            return
        spent = self.spent_week(now)
        projected = spent + float(est_cost_usd)
        if projected > self.weekly_cap:
            raise BudgetExceeded(
                f"{service}: projected ${projected:.2f} exceeds weekly cap "
                f"${self.weekly_cap:.2f} (already spent ${spent:.2f} this week)")
