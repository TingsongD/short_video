"""M11 CLI — backs run.sh.

  python -m modules.orchestrate produce <idea_id>   M4->M9, gated
  python -m modules.orchestrate readback            due analytics windows
  python -m modules.orchestrate weekly              M1->M2->M3 + shortlist
  python -m modules.orchestrate approve <scope>     grant a spend/publish token
  python -m modules.orchestrate cron-line|install-cron
  python -m modules.orchestrate ledger              print weekly spend
"""
import argparse
import sys
from pathlib import Path

from modules.common.config import DATA_DIR, ROOT
from modules.orchestrate import approval, pipeline, schedule, stages
from modules.orchestrate.ledger import LEDGER_PATH, CostLedger


def _ctx(args):
    cfg = _load_config()
    ledger = CostLedger(weekly_cap=cfg["costs"]["weekly_cap_usd"])
    ctx = {
        "config": cfg,
        "ledger": ledger,
        "hooks_path": DATA_DIR / "hooks" / "bank.json",
        "formats_path": DATA_DIR / "formats" / "library.json",
        "est": _estimates(cfg),
    }
    if args.cmd == "produce":
        ctx.update(_live_production_clients(cfg))
    elif args.cmd == "readback":
        ctx["analytics_client"] = _live_analytics_client(cfg)
        from modules.common.config import secrets
        ctx["channel_handle"] = secrets().get("YT_CHANNEL_HANDLE", "")
    elif args.cmd == "weekly":
        ctx.update(_live_weekly_clients(cfg))
    return ctx


def _load_config():
    from modules.common.config import system
    return system()


def _estimates(cfg):
    return {"llm": 0.05, "elevenlabs": 0.20}


def _live_production_clients(cfg):
    """Real externals — constructed lazily so `run.sh produce` fails at the
    gate, not at import time, when keys are missing."""
    from modules.common.config import secrets
    from modules.common.llm import LLMClient
    from modules.voice.tts import ElevenLabsTTS
    from modules.assets.pexels import PexelsClient

    sec = secrets()
    return {
        "llm": LLMClient.from_secrets(sec),
        "tts": ElevenLabsTTS(
            sec.get("ELEVENLABS_API_KEY", ""), cfg["voice"]["voice_id"],
            model=cfg["voice"]["model"]),
        "pexels": PexelsClient(sec.get("PEXELS_API_KEY", "")),
        "mpt_runner": None,
        "uploader": _live_uploader(sec),
    }


def _live_uploader(sec):
    from modules.publish.uploader import manual_instructions, upload_post
    key = sec.get("UPLOAD_POST_API_KEY", "")
    if not key:
        def missing(video_path, meta):
            raise RuntimeError(
                "no upload mechanism configured — set UPLOAD_POST_API_KEY in "
                "secrets.toml or publish manually per docs/publish-manual.md")
        return missing
    return lambda video_path, meta: upload_post(video_path, meta, key)


def _live_analytics_client(cfg):
    from modules.common.config import secrets
    from modules.analytics.pull import AnalyticsClient
    sec = secrets()
    return AnalyticsClient(
        yt_api_key=sec.get("YOUTUBE_API_KEY", ""),
        oauth_token_path=sec.get("YT_ANALYTICS_TOKEN", ""))


def _live_weekly_clients(cfg):
    from modules.common.config import niches, secrets
    from modules.common.llm import LLMClient
    from modules.grill.gate import run as grill_run
    from modules.radar.client import YouTubeClient
    from modules.radar.quota import QuotaManager
    from modules.radar.scanner import scan

    sec = secrets()
    ncfg = niches()
    client = YouTubeClient(
        sec.get("YOUTUBE_API_KEY", ""),
        QuotaManager(cfg["radar"]["daily_quota_budget"]))
    llm = LLMClient.from_secrets(sec)

    def radar_scan():
        """B4 fix: compose scan -> build_report -> write_report so the grill
        receives the niche_report CONTRACT shape (raw scan output has no
        'niches' key and silently produced empty shortlists), and the G1
        evidence artifact lands in data/radar/."""
        from datetime import date

        from modules.radar.report import build_report, write_report

        result = scan(client, ncfg["niche"], cfg["radar"])
        report = build_report(
            result["clusters"], result["scanned_at"],
            [n["name"] for n in ncfg["niche"]], client.quota.used,
            degraded=result.get("degraded", False))
        write_report(report, DATA_DIR / "radar", date.today().isoformat())
        return report

    return {
        "radar_scan": radar_scan,
        "grill_run": lambda report: grill_run(
            report, llm, cfg["grill"]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orchestrate")
    ap.add_argument("cmd", choices=["produce", "readback", "weekly",
                                    "approve", "cron-line", "install-cron",
                                    "ledger"])
    ap.add_argument("arg", nargs="?")
    args = ap.parse_args(argv)

    if args.cmd == "approve":
        if not args.arg:
            ap.error("approve requires a scope (e.g. spend, publish)")
        p = approval.grant(args.arg)
        print(f"approved scope '{args.arg}' -> {p}")
        return 0
    if args.cmd == "cron-line":
        print(schedule.cron_line())
        return 0
    if args.cmd == "install-cron":
        print(schedule.install())
        return 0
    if args.cmd == "ledger":
        led = CostLedger()
        cfg = _load_config()
        cap = cfg["costs"]["weekly_cap_usd"]
        print(f"ledger: {LEDGER_PATH}")
        print(f"entries: {len(led.entries)}  "
              f"week spend: ${led.spent_week():.4f} / ${cap:.2f}")
        return 0

    ctx = _ctx(args)
    if args.cmd == "produce":
        if not args.arg:
            ap.error("produce requires an idea_id")
        st = stages.produce_stages(args.arg, ctx)
    elif args.cmd == "readback":
        st = stages.readback_stages(ctx)
    else:
        st = stages.weekly_stages(ctx)

    record = pipeline.run_stages(args.cmd, st)
    print(f"{args.cmd}: {record['status']} (log: {record['log_path']})")
    for s in record["stages"]:
        mark = "ok" if s["status"] == "ok" else f"FAILED: {s['error']}"
        print(f"  {s['name']:<10} {mark}")
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
