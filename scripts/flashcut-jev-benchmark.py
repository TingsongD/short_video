#!/usr/bin/env python3
"""Score a sanitized Jev shadow-case file without provider or DB access."""
import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(source, destination):
    if destination.exists():
        raise SystemExit("Refusing to overwrite an existing benchmark report.")
    try:
        payload = json.loads(source.read_text())
        cases = payload["cases"]
    except (OSError, KeyError, TypeError, ValueError,
            json.JSONDecodeError) as error:
        raise SystemExit("Invalid sanitized benchmark input.") from error
    from modules.factory.analysis.jev_benchmark import (
        evaluate_shadow_benchmark,
    )
    report = evaluate_shadow_benchmark(cases)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "qualified": report["qualified"],
        "disqualifiers": report["disqualifiers"],
        "report_sha256": report["report_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    main(args.source.resolve(), args.destination.resolve())
