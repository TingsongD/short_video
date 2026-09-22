"""Consistent, owner-only rollout snapshot; never restore over active data.

Contains a SQLite backup and sanitized fingerprints, not logs or credentials.
Run before an idle-service rollout. Existing backup directories are refused.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3


def snapshot(root, destination):
    os.umask(0o077)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = sqlite3.connect((root/'data/factory/factory.db').resolve().as_uri()+'?mode=ro', uri=True)
    target = sqlite3.connect(destination/'factory.db')
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Snapshot integrity check failed')
        active = target.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('succeeded','failed','blocked','cancelled','awaiting_review')").fetchone()[0]
    finally:
        target.close()
        source.close()
    spec = importlib.util.spec_from_file_location('factory_rollout_audit', Path(__file__).with_name('factory-qa-audit.py'))
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    report = audit.audit(root, destination/'factory.db')
    report['active_jobs'] = active
    report['database_integrity'] = 'ok'
    (destination/'fingerprints.json').write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({'backup':str(destination), 'active_jobs':active, 'finals':len(report['finals']),
                      'all_final_hashes_match':all(f['matches'] for f in report['finals'])}))
    if active:
        raise RuntimeError('Snapshot retained, but rollout must wait for active jobs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--root', default='.', type=Path)
    args = parser.parse_args()
    snapshot(args.root.resolve(), args.destination.resolve())
