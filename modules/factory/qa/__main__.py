"""QA harness CLI (runbook §3).

  python -m modules.factory.qa init --workspace W --fixture core-30s
  python -m modules.factory.qa cases [--module F05] [--json]
  python -m modules.factory.qa run --workspace W --case F05-M01 \
      [--mode offline] [--run-id R] [--authorization-id A]
  python -m modules.factory.qa inspect --workspace W --view budgets [--json]
  python -m modules.factory.qa evidence --workspace W --module F05
"""
import argparse
import json
import sys
from pathlib import Path

from . import workspace as ws
from . import views
from .evidence import new_record, save
from .registry import all_cases, case_status, LIVE_CASES, CONNECTED_CASES
from ..testing.clock import FakeClock, utcnow_iso

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def _print(doc, as_json):
    if as_json:
        print(json.dumps(doc, indent=1, sort_keys=True))
    elif isinstance(doc, str):
        print(doc)
    else:
        print(json.dumps(doc, indent=1, sort_keys=True))


def cmd_init(args):
    try:
        meta = ws.init(args.workspace, args.fixture)
    except ws.WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAIL
    _print({"initialized": args.workspace, "fixture": meta["fixture"]},
           args.json)
    return EXIT_OK


def cmd_cases(args):
    specs = all_cases()
    rows = []
    for spec in specs.values():
        if args.module and spec.module != args.module:
            continue
        rows.append({"case": spec.id, "module": spec.module,
                     "level": spec.level, "status": case_status(spec),
                     "expected": spec.expected})
    if args.json:
        _print(rows, True)
    else:
        for r in rows:
            print(f"{r['case']:12} {r['level']:9} {r['status']:20} "
                  f"{r['expected']}")
    return EXIT_OK


def cmd_run(args):
    specs = all_cases()
    spec = specs.get(args.case)
    if spec is None:
        print(f"error: unknown case {args.case!r}", file=sys.stderr)
        return EXIT_FAIL
    mode = args.mode
    if mode == "live":
        if args.case not in LIVE_CASES:
            print(f"error: {args.case} is not registered for live mode",
                  file=sys.stderr)
            return EXIT_FAIL
        if not args.authorization_id:
            print("error: --mode live requires --authorization-id naming an "
                  "existing authorization record; the harness cannot create "
                  "spending authority", file=sys.stderr)
            return EXIT_FAIL
    elif mode == "connected" and args.case not in CONNECTED_CASES:
        print(f"error: {args.case} is not registered for connected mode",
              file=sys.stderr)
        return EXIT_FAIL

    try:
        workspace = ws.open_workspace(args.workspace)
    except ws.WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAIL

    status = case_status(spec)
    if status != "implemented":
        print(f"error: case {args.case} is {status} (needs module "
              f"{spec.module})", file=sys.stderr)
        return EXIT_FAIL

    run_id = args.run_id or workspace.ids.next(f"run-{args.case}")
    run_dir = workspace.run_dir(args.case, run_id)
    record_path = run_dir / "run.json"
    if record_path.exists():
        # Repeating an existing run ID is idempotent: report, never re-execute.
        doc = json.loads(record_path.read_text())
        print(f"run {run_id} already recorded as {doc['status']}; "
              "idempotent replay does not duplicate effects")
        _print(doc, args.json)
        return EXIT_OK if doc["status"] in ("passed", "awaiting_manual_review") \
            else EXIT_FAIL

    clock = workspace.clock()
    ctx_mod = __import__("modules.factory.qa.cases_f01", fromlist=["CaseContext"])
    ctx = ctx_mod.CaseContext(workspace, run_dir, mode, clock)

    rec = new_record(spec.id, spec.module, mode, spec.expected,
                     workspace.fixture)
    rec["run_id"] = run_id
    rec["started_at"] = utcnow_iso()
    try:
        result = spec.impl(ctx)
    except Exception as e:  # a case crash is a failed run, not a pass
        rec.update(status="failed", actual=f"case raised {type(e).__name__}: {e}",
                   finished_at=utcnow_iso())
        save(workspace.path, rec)
        (run_dir / "run.json").write_text(json.dumps(rec, indent=1))
        print(f"error: case raised {e}", file=sys.stderr)
        return EXIT_FAIL

    rec.update(status=result["status"], actual=result["actual"],
               assertions=result["assertions"], artifacts=result["artifacts"],
               provider_submission_count=result["provider_submission_count"],
               limitations=result["limitations"],
               cleanup_receipt=result.get("cleanup_receipt"),
               finished_at=utcnow_iso())
    save(workspace.path, rec)
    (run_dir / "run.json").write_text(json.dumps(rec, indent=1, sort_keys=True))
    _print(rec, args.json)
    return EXIT_OK if rec["status"] in ("passed", "awaiting_manual_review") \
        else EXIT_FAIL


def cmd_inspect(args):
    try:
        workspace = ws.open_workspace(args.workspace)
        out = views.inspect(workspace, args.view)
    except (ws.WorkspaceError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAIL
    _print(out, args.json)
    return EXIT_OK if out.get("status") == "ok" else EXIT_FAIL


def cmd_evidence(args):
    try:
        workspace = ws.open_workspace(args.workspace)
    except ws.WorkspaceError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAIL
    base = workspace.path / "evidence" / args.module
    records = sorted(base.glob("**/*.json")) if base.exists() else []
    bundle = {"module": args.module,
              "records": [str(r.relative_to(workspace.path)) for r in records],
              "sha256": {r.stem: __import__("hashlib").sha256(
                  r.read_bytes()).hexdigest() for r in records}}
    _print(bundle, args.json)
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(prog="modules.factory.qa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--workspace", required=True)
    p.add_argument("--fixture", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("cases")
    p.add_argument("--module")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_cases)
    p = sub.add_parser("run")
    p.add_argument("--workspace", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--mode", default="offline",
                   choices=("offline", "connected", "live"))
    p.add_argument("--run-id")
    p.add_argument("--authorization-id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("inspect")
    p.add_argument("--workspace", required=True)
    p.add_argument("--view", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_inspect)
    p = sub.add_parser("evidence")
    p.add_argument("--workspace", required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_evidence)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
