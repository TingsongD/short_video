"""Radar discovery: free checks, reviewable search plans, and bounded scans."""
import argparse
from datetime import datetime, timezone
import json
import sys

from modules.common.config import DATA_DIR, niches, secrets, system
from modules.orchestrate.ledger import CostLedger
from .service import discover
from .viral_client import ViralError, ViralOutliersClient
from .viral_scan import load_plan, prepare, preview, run_dir, save_json


def main(argv=None):
    p = argparse.ArgumentParser(description="Find outliers using views / followers > 2")
    p.add_argument("command", nargs="?", choices=["doctor", "preview", "plan", "scan", "resume"])
    p.add_argument("--provider", choices=["viral-outliers", "youtube"])
    p.add_argument("--run-id", help="saved batch to prepare, run, or resume")
    p.add_argument("--credit-ceiling", type=int, help="approve the reviewed batch's maximum API credits")
    p.add_argument("--niche", action="append", help="configured niche name (repeat to select several)")
    p.add_argument("--query", help="one custom keyword; requires exactly one selected niche")
    p.add_argument("--platform", action="append", choices=["youtube", "tiktok"])
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--date", help="YouTube scan date YYYY-MM-DD (default: today, UTC)")
    p.add_argument("--budget", type=int, help="YouTube daily quota budget")
    args = p.parse_args(argv)
    try:
        cfg = system()
        provider = args.provider or cfg["radar"].get("provider", "youtube")
        command = args.command or ("plan" if provider == "viral-outliers" else "scan")
        selected = niches()["niche"]
        if args.niche:
            unknown = set(args.niche) - {n["name"] for n in selected}
            if unknown:
                raise ViralError("Unknown niche name: " + ", ".join(sorted(unknown)))
            selected = [dict(n) for n in selected if n["name"] in args.niche]
        if args.query:
            if len(selected) != 1:
                raise ViralError("--query requires exactly one --niche")
            selected[0] = {**selected[0], "keywords": [args.query]}
        root = DATA_DIR / "radar" / "viral-outliers"
        if provider == "viral-outliers" and (args.date or args.budget):
            raise ViralError("--date and --budget apply only to the YouTube provider")
        if provider == "youtube" and command != "scan":
            raise ViralError("Use --provider youtube scan for the native YouTube scanner")
        if command in ("scan", "resume") and provider == "viral-outliers":
            if not args.run_id:
                raise ViralError("Run plan first, then pass its --run-id and reviewed --credit-ceiling")
            if args.query or args.niche or args.platform or args.pages != 1 or args.page_size != 100:
                raise ViralError("Scan/resume uses the saved plan; set query options when preparing a new plan")
            load_plan(root, args.run_id)
        if command == "plan":
            run_id = args.run_id or f"weekly-{datetime.now(timezone.utc).date().isoformat()}"
            plan = prepare(root, run_id, selected, cfg["radar"],
                           platforms=args.platform or cfg["radar"].get("platforms"),
                           pages=args.pages, page_size=args.page_size)
            print(json.dumps(plan, indent=2))
            print(f"Saved: {run_dir(root, run_id) / 'plan.json'}")
            print(f"After review: python -m modules.radar scan --run-id {run_id} "
                  f"--credit-ceiling {plan['credit_quote']}")
            return 0
        client = ViralOutliersClient(secrets().get("VIRAL_OUTLIERS_API_KEY", ""))
        if command == "doctor":
            result = client.doctor()
            save_json(root / "doctor.json", result)
            print(json.dumps(result, indent=2))
            return 0
        if command == "preview":
            result = preview(client, cfg["radar"])
            save_json(root / "free-preview.json", result)
            print(json.dumps({k: v for k, v in result.items() if k != "observations"}, indent=2))
            print(f"Browsing evidence: {root / 'free-preview.json'}")
            return 0
        now = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc) if args.date else None
        report = discover(cfg, selected, secrets(), provider=provider, run_id=args.run_id,
                          credit_ceiling=args.credit_ceiling, now=now, quota_budget=args.budget,
                          ledger=CostLedger(weekly_cap=cfg["costs"]["weekly_cap_usd"]))
        print(json.dumps(report["scan_meta"], indent=2))
        print(f"{sum(n['confirmed'] for n in report['niches'])} confirmed topic clusters")
        print(f"Report: {DATA_DIR / 'radar' / (report['scan_meta']['scanned_at'][:10] + '.json')}")
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
