"""Read-only rollout fingerprints; output contains hashes/counts, never payloads."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def audit(root, database_path=None):
    db = sqlite3.connect((database_path or root/'data/factory/factory.db').resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    result = {'tables':{}, 'finals':[], 'job_counts':{}}
    for name in ('records','jobs','artifacts','budgets','reservations','reservation_lines','attempts','effect_bindings'):
        rows = [dict(r) for r in db.execute('SELECT * FROM '+name)]
        result['tables'][name] = {'count':len(rows), 'sha256':digest(sorted(rows,key=lambda r:json.dumps(r,sort_keys=True,default=str)))}
    finals = list(db.execute("SELECT key,value FROM meta WHERE key LIKE 'final:%' ORDER BY key"))
    result['final_bindings_sha256'] = digest([dict(r) for r in finals])
    for row in finals:
        final = json.loads(row['value'])
        art = db.execute('SELECT local_path,sha256 FROM artifacts WHERE id=?',(final['artifact_id'],)).fetchone()
        path = Path(art['local_path'])
        if not path.is_absolute():
            path = root/'data/factory/artifacts'/path
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        result['finals'].append({'binding':row['key'], 'sha256':h.hexdigest(),
            'matches':h.hexdigest()==final['sha256']==art['sha256']})
    result['job_counts'] = dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
    db.close()
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',default='.')
    args=parser.parse_args()
    print(json.dumps(audit(Path(args.root)),sort_keys=True))
