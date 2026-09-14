"""M9 publish records + cadence guardrail.

Records live at data/published/<video_id>.json (schema publish_record).
Duplicate video_ids are rejected — M10 readback depends on unique files.
Cadence: max_posts_per_day per platform, from system.toml [publish].
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from modules.common.config import DATA_DIR
from modules.common.schema import validate

PUBLISHED_DIR = DATA_DIR / "published"


def load_records(directory=None):
    d = Path(directory or PUBLISHED_DIR)
    if not d.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]


def write_record(record, directory=None):
    d = Path(directory or PUBLISHED_DIR)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['video_id']}.json"
    if p.exists():
        raise FileExistsError(f"publish record already exists: {record['video_id']}")
    validate(record, "publish_record.schema.json")
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return p


def posts_on(records, platform, day):
    """Count records published on `day` (date) containing `platform`."""
    count = 0
    for r in records:
        if platform not in r.get("platform_video_ids", {}):
            continue
        pub = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
        if pub.date() == day:
            count += 1
    return count


def check_cadence(records, platform, when=None, max_per_day=2):
    """Raise CadenceBlock if posting now would exceed the daily cap."""
    when = when or datetime.now(timezone.utc)
    n = posts_on(records, platform, when.date())
    if n >= max_per_day:
        raise CadenceBlock(
            f"{platform}: {n} posts on {when.date()} hits cap {max_per_day}"
        )
    return True


class CadenceBlock(Exception):
    pass
