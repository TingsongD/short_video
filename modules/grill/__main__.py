"""CLI: python -m modules.grill <niche_report.json> [--ideas candidates.json]
Runs the grill on a radar report and writes data/grill/<date>.json.
LLM-backed — needs LLM_* keys in config/secrets.toml (Wave 3 approval)."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from modules.common.config import DATA_DIR, secrets, system
from modules.common.llm import LLMClient
from modules.common.schema import validate

from .gate import build_output, run


def main(argv=None):
    p = argparse.ArgumentParser(description="M2 Idea Grill — score and kill")
    p.add_argument("report", help="path to a niche_report JSON")
    p.add_argument(
        "--ideas",
        help="pre-generated candidates JSON (skip LLM expansion; still judged)",
    )
    args = p.parse_args(argv)

    report = json.loads(Path(args.report).read_text())
    cfg = system()["grill"]
    llm = LLMClient.from_secrets(secrets())

    if args.ideas:
        candidates = json.loads(Path(args.ideas).read_text())["candidates"]
        doc, audit = build_output(candidates, llm, cfg, source_report=args.report)
    else:
        doc, audit = run(report, llm, cfg, source_report=args.report)

    validate(doc, "scored_ideas.schema.json")
    date_str = doc["generated_at"][:10]
    out = Path(DATA_DIR / "grill" / f"{date_str}.json")
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / f"grill-{date_str}.jsonl", "a", encoding="utf-8") as f:
        for a in audit:
            f.write(json.dumps(a) + "\n")

    n_pass = sum(1 for i in doc["ideas"] if i["status"] == "pass")
    print(f"scored_ideas: {out}")
    print(f"{n_pass}/{len(doc['ideas'])} passed (audit log: logs/grill-{date_str}.jsonl)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
