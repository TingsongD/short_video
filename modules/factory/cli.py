"""Factory operations CLI (F30): doctor, config, services, backup,
restore. `python -m modules.factory.cli <command>`.

Never embeds credentials; live-service checks are read-only.
"""
import argparse
import json
import sys
from pathlib import Path

from .operations import (ServiceManager, activation_gate, create_backup,
                         dispatch_gate, doctor, load_config,
                         restore_into)
from .resources import ResourceRegistry
from .store import Database


def _db(root):
    from .operations.paths import database_path
    path = database_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Database(path)


def main(argv=None):
    p = argparse.ArgumentParser(prog="factory")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("config")
    st = sub.add_parser("start"); st.add_argument("service")
    st.add_argument("--port", type=int, required=True)
    st.add_argument("--alt", type=int, action="append", default=[])
    st.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    sp = sub.add_parser("stop"); sp.add_argument("service")
    sub.add_parser("drain")
    sub.add_parser("gate")
    b = sub.add_parser("backup"); b.add_argument("dest")
    b.add_argument("--ledger", action="append", default=[])
    r = sub.add_parser("restore"); r.add_argument("backup_dir")
    r.add_argument("new_root")
    args = p.parse_args(argv)
    root = Path(args.root)

    if args.cmd == "doctor":
        out = doctor(root)
        print(json.dumps(out, indent=1))
        return 0 if out["ok"] else 1
    if args.cmd == "config":
        out = load_config(root)
        print(json.dumps(out, indent=1))
        return 0
    if args.cmd == "gate":
        out = dispatch_gate(_db(root))
        print(json.dumps(out, indent=1))
        return 0 if out["allowed"] else 1

    mgr = ServiceManager(ResourceRegistry(_db(root)))
    if args.cmd == "start":
        if not args.argv:
            print("error: start requires an argv", file=sys.stderr)
            return 2
        out = mgr.start(args.service, args.argv, str(root),
                        args.port, args.alt)
        print(json.dumps(out, indent=1))
        return 0
    if args.cmd == "status":
        print(json.dumps(mgr.status(), indent=1))
        return 0
    if args.cmd == "stop":
        print(json.dumps(mgr.stop(args.service), indent=1))
        return 0
    if args.cmd == "drain":
        from .scheduler import Scheduler
        print(json.dumps(mgr.drain(Scheduler(_db(root))), indent=1))
        return 0
    if args.cmd == "backup":
        out = create_backup(_db(root), root, args.dest,
                            ledger_paths=args.ledger)
        print(json.dumps(out, indent=1))
        return 0
    if args.cmd == "restore":
        out = restore_into(args.backup_dir, args.new_root)
        print(json.dumps(out, indent=1))
        db = _db(args.new_root)
        gate = activation_gate(db)
        print(json.dumps({"activation": gate}, indent=1))
        return 0 if not gate["pending_effects"] else 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
