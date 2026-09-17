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
    serve=sub.add_parser("serve"); serve.add_argument("--port",type=int,default=5184)
    worker=sub.add_parser("worker"); worker.add_argument("--once",action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("config")
    st = sub.add_parser("start"); st.add_argument("service")
    st.add_argument("--port", type=int)
    st.add_argument("--alt", type=int, action="append", default=[])
    st.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    sp = sub.add_parser("stop"); sp.add_argument("service")
    sub.add_parser("drain")
    sub.add_parser("gate")
    activation=sub.add_parser("activate-restore"); activation.add_argument("evidence")
    b = sub.add_parser("backup"); b.add_argument("dest")
    b.add_argument("--ledger", action="append", default=[])
    r = sub.add_parser("restore"); r.add_argument("backup_dir")
    r.add_argument("new_root")
    args = p.parse_args(argv)
    root = Path(args.root)

    if args.cmd in ("serve","worker"):
        from .bootstrap import bootstrap
        services=bootstrap(root)
        if args.cmd=="serve":
            from .api import create_app
            import uvicorn
            uvicorn.run(create_app(services),host="127.0.0.1",port=args.port,timeout_graceful_shutdown=5)
        else:
            from .services.worker import ApplicationWorker
            ApplicationWorker(services).run(once=args.once)
        return 0
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

    if args.cmd == 'activate-restore':
        from .operations.reconcile import activate_restore
        from .artifacts.registry import ArtifactStore
        from .operations.paths import data_root
        db=_db(root)
        print(json.dumps(activate_restore(db,ArtifactStore(data_root(root)/'artifacts',db),json.loads(Path(args.evidence).read_text())),indent=1))
        return 0
    mgr = ServiceManager(ResourceRegistry(_db(root)))
    if args.cmd == "start":
        if not args.argv:
            print("error: start requires an argv", file=sys.stderr)
            return 2
        argv=args.argv[1:] if args.argv[0]=='--' else args.argv
        out = mgr.start(args.service, argv, str(root),
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
