"""M11 CLI — backs run.sh.

  python -m modules.orchestrate produce <idea_id>   M4->M9, gated
  python -m modules.orchestrate readback            due analytics windows
  python -m modules.orchestrate weekly              M1->M2->M3 + shortlist
  python -m modules.orchestrate approve <scope>     grant a spend/publish token
  python -m modules.orchestrate cron-line|install-cron
  python -m modules.orchestrate ledger              print weekly spend
"""
import argparse
import json
import sys
from pathlib import Path
from contextlib import nullcontext

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
        ctx.update(resume=args.resume, stop_after="publish" if args.publish else args.stop_after,
                   video_id=args.video_id, asset_provider=args.asset_provider or
                   cfg.get("assets", {}).get("provider", "jimeng-canvas"),
                   asset_fallback=args.asset_fallback, jimeng_credit_ceiling=args.jimeng_credit_ceiling)
    elif args.cmd == "readback":
        ctx["analytics_client"] = _live_analytics_client(cfg)
        from modules.common.config import secrets
        ctx["channel_handle"] = secrets().get("YT_CHANNEL_HANDLE", "")
    elif args.cmd == "weekly":
        ctx.update(_live_weekly_clients(
            cfg, ledger=ledger, provider=args.radar_provider,
            run_id=args.radar_run_id, credit_ceiling=args.radar_credit_ceiling))
    return ctx


def _load_config():
    from modules.common.config import system
    return system()


def _estimates(cfg):
    return {"llm": 0.05, "elevenlabs": 0.20}


class _LazyClient:
    def __init__(self, factory):
        self.factory, self.client = factory, None

    def __getattr__(self, name):
        if self.client is None:
            self.client = self.factory()
        return getattr(self.client, name)


def _live_production_clients(cfg):
    """Real externals — constructed lazily so `run.sh produce` fails at the
    gate, not at import time, when keys are missing."""
    from modules.common.config import secrets
    from modules.common.llm import LLMClient
    from modules.voice.tts import ElevenLabsTTS
    from modules.assets.pexels import PexelsClient

    sec = secrets()
    return {
        "llm": _LazyClient(lambda: LLMClient.from_secrets(sec)),
        "tts": _LazyClient(lambda: ElevenLabsTTS(
            sec.get("ELEVENLABS_API_KEY", ""), cfg["voice"]["voice_id"],
            model=cfg["voice"]["model"])),
        "pexels": (_LazyClient(lambda: PexelsClient(sec["PEXELS_API_KEY"]))
                   if sec.get("PEXELS_API_KEY") else None),
        "mpt_runner": None,
        "uploader": _live_uploader(sec),
    }


def _live_uploader(sec):
    from modules.publish.uploader import manual_instructions, upload_post
    key = sec.get("UPLOAD_POST_API_KEY", "")
    user = sec.get("UPLOAD_POST_USER", "")
    if not key or not user:
        def missing(video_path, meta):
            raise RuntimeError(
                "no upload mechanism configured — set UPLOAD_POST_API_KEY "
                "and UPLOAD_POST_USER in secrets.toml or publish manually "
                "per docs/publish-manual.md")
        return missing
    return lambda video_path, meta: upload_post(video_path, meta, key,
                                                user=user)


def _live_analytics_client(cfg):
    from modules.common.config import secrets
    from modules.analytics.pull import AnalyticsClient
    sec = secrets()
    return AnalyticsClient(
        yt_api_key=sec.get("YOUTUBE_API_KEY", ""),
        oauth_token_path=sec.get("YT_ANALYTICS_TOKEN", ""))


def _live_weekly_clients(cfg, *, ledger=None, provider=None, run_id=None, credit_ceiling=None):
    from modules.common.config import niches, secrets
    from modules.common.llm import LLMClient
    from modules.grill.gate import run as grill_run
    from modules.radar.service import discover

    sec = secrets()
    ncfg = niches()
    llm = _LazyClient(lambda: LLMClient.from_secrets(sec))
    return {
        "radar_scan": lambda: discover(
            cfg, ncfg["niche"], sec, provider=provider, run_id=run_id,
            credit_ceiling=credit_ceiling, ledger=ledger),
        "grill_run": lambda report: grill_run(report, llm, cfg["grill"]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orchestrate")
    ap.add_argument("cmd", choices=["produce", "readback", "weekly",
                                    "approve", "cron-line", "install-cron",
                                    "ledger"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--resume", action="store_true", help="reuse saved script and validated artifacts")
    ap.add_argument("--video-id", help="explicit new production ID")
    ap.add_argument("--stop-after", choices=["assets", "qc"], default="qc")
    ap.add_argument("--publish", action="store_true", help="continue through the separate publishing gate")
    ap.add_argument("--asset-provider", choices=["jimeng-canvas", "manual"])
    ap.add_argument("--asset-fallback", choices=["none", "stock"], default="none")
    ap.add_argument("--jimeng-credit-ceiling", type=int,
                    help="explicit approval of a previously reviewed Jimeng batch quote")
    ap.add_argument("--radar-provider", choices=["viral-outliers", "youtube"])
    ap.add_argument("--radar-run-id", help="prepared discovery batch to use for weekly")
    ap.add_argument("--radar-credit-ceiling", type=int,
                    help="approve the reviewed Viral Outliers search batch")
    args = ap.parse_args(argv)
    if args.publish and args.stop_after == "assets":
        ap.error("--publish cannot be combined with --stop-after assets")
    if args.jimeng_credit_ceiling is not None and args.jimeng_credit_ceiling < 0:
        ap.error("--jimeng-credit-ceiling must be nonnegative")

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
    lock = nullcontext()
    if args.cmd == "produce":
        if not args.arg:
            ap.error("produce requires an idea_id")
        from modules.assets.queue import validate_video_id
        from modules.orchestrate.checkpoint import production_lock
        video_id = args.video_id or f"v-{args.arg}"
        validate_video_id(video_id)
        lock = production_lock(DATA_DIR / "production" / video_id)
    with lock:
        if args.cmd == "produce":
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
        if s.get("details"):
            print(json.dumps(s["details"], indent=2))
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
