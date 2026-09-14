"""CLI: python -m modules.radar [--date YYYY-MM-DD] [--budget N]
Runs a LIVE scan — needs YOUTUBE_API_KEY in config/secrets.toml."""
import argparse
import sys
from datetime import datetime, timezone

from modules.common.config import DATA_DIR, niches, secrets, system
from modules.common.schema import validate

from .client import YouTubeClient
from .quota import QuotaManager
from .report import build_report, write_report
from .scanner import scan


def main(argv=None):
    p = argparse.ArgumentParser(description="M1 Niche Radar — weekly outlier scan")
    p.add_argument("--date", help="scan date YYYY-MM-DD (default: today, UTC)")
    p.add_argument("--budget", type=int, help="override daily quota budget")
    args = p.parse_args(argv)

    key = secrets().get("YOUTUBE_API_KEY", "")
    if not key:
        print("YOUTUBE_API_KEY missing in config/secrets.toml", file=sys.stderr)
        return 1

    cfg = system()
    budget = args.budget or cfg["radar"]["daily_quota_budget"]
    client = YouTubeClient(key, quota=QuotaManager(budget))

    now = (
        datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
        if args.date
        else datetime.now(timezone.utc)
    )
    result = scan(client, niches()["niche"], cfg["radar"], now=now)
    report = build_report(
        result["clusters"],
        result["scanned_at"],
        [n["name"] for n in niches()["niche"]],
        client.quota.used,
        degraded=result["degraded"],
    )
    validate(report, "niche_report.schema.json")
    date_str = result["scanned_at"].date().isoformat()
    json_path, md_path = write_report(report, DATA_DIR / "radar", date_str)
    n_confirmed = sum(1 for n in report["niches"] if n["confirmed"])
    print(f"report: {json_path}\nsummary: {md_path}")
    print(
        f"{len(report['niches'])} cluster entries, {n_confirmed} confirmed, "
        f"{client.quota.used} quota units"
        + (" [DEGRADED]" if result["degraded"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
