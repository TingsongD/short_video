"""Shared provider selection for the radar CLI and weekly shortlist."""
from datetime import datetime, timezone

from modules.common.config import DATA_DIR
from modules.common.schema import validate
from .report import build_report, write_report


def discover(cfg, niche_configs, secret_values, *, provider=None, run_id=None,
             credit_ceiling=None, ledger=None, now=None, quota_budget=None):
    provider = provider or cfg["radar"].get("provider", "youtube")
    now = now or datetime.now(timezone.utc)
    if provider == "viral-outliers":
        from .viral_client import ViralOutliersClient
        from .viral_scan import execute, prepare, run_dir
        root = DATA_DIR / "radar" / "viral-outliers"
        run_id = run_id or f"weekly-{now.date().isoformat()}"
        if not (run_dir(root, run_id) / "plan.json").exists():
            prepare(root, run_id, niche_configs, cfg["radar"],
                    platforms=cfg["radar"].get("platforms", ["youtube", "tiktok"]))
        client = ViralOutliersClient(secret_values.get("VIRAL_OUTLIERS_API_KEY", ""))
        report = execute(root, run_id, client, credit_ceiling=credit_ceiling, ledger=ledger)
    elif provider == "youtube":
        from .client import YouTubeClient
        from .quota import QuotaManager
        from .scanner import scan
        key = secret_values.get("YOUTUBE_API_KEY", "")
        if not key:
            raise ValueError("YOUTUBE_API_KEY is missing; set it in the project .env or secrets.toml")
        client = YouTubeClient(key, quota=QuotaManager(
            quota_budget if quota_budget is not None else cfg["radar"]["daily_quota_budget"]))
        result = scan(client, niche_configs, cfg["radar"], now=now)
        report = build_report(result["clusters"], result["scanned_at"],
                              [n["name"] for n in niche_configs], client.quota.used,
                              degraded=result["degraded"])
        report["scan_meta"]["provider"] = "youtube"
        report["scan_meta"]["eligibility"] = cfg["radar"].get("eligibility", "median_and_followers")
    else:
        raise ValueError("Unsupported radar provider")
    validate(report, "niche_report.schema.json")
    write_report(report, DATA_DIR / "radar", report["scan_meta"]["scanned_at"][:10])
    return report
