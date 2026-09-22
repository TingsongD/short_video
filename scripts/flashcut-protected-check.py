"""Read-only comparison to a consistent pre-change SQLite backup.

New acceptance rows are permitted; every pre-existing protected row, final
binding and final file must remain identical. No database is ever restored.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

TABLES=('records','jobs','artifacts','budgets','reservations','reservation_lines','attempts','effect_bindings')


def connect(path):
    result=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    result.row_factory=sqlite3.Row
    return result


def compare(baseline,current,artifact_root):
    before,after=connect(baseline),connect(current)
    try:
        tables={}
        for name in TABLES:
            primary=[r['name'] for r in sorted(before.execute('PRAGMA table_info('+name+')'),key=lambda r:r['pk']) if r['pk']]
            if not primary:raise ValueError('Protected table has no stable primary key.')
            query='SELECT * FROM '+name+' WHERE '+' AND '.join('"'+key+'"=?' for key in primary)
            rows=list(before.execute('SELECT * FROM '+name));changed=0
            for row in rows:
                saved=after.execute(query,tuple(row[k] for k in primary)).fetchone()
                changed+=saved is None or dict(saved)!=dict(row)
            tables[name]={'protected_rows':len(rows),'modified_or_missing':changed}
        finals=[]
        for row in before.execute("SELECT key,value FROM meta WHERE key LIKE 'final:%' ORDER BY key"):
            value=json.loads(row['value'])
            binding=after.execute('SELECT value FROM meta WHERE key=?',(row['key'],)).fetchone()
            original=before.execute('SELECT local_path,sha256 FROM artifacts WHERE id=?',(value['artifact_id'],)).fetchone()
            if not original:raise ValueError('Baseline final artifact is unavailable.')
            path=Path(original['local_path'])
            if not path.is_absolute():path=artifact_root/path
            with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
            finals.append({'binding':row['key'],'unchanged':bool(binding and binding['value']==row['value']
                and sha==original['sha256']==value['sha256'])})
        return {'version':'protected_state_check.v1','tables':tables,'finals':finals,
            'unchanged':all(not t['modified_or_missing'] for t in tables.values()) and all(f['unchanged'] for f in finals)}
    finally:before.close();after.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--current',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=compare(args.baseline,args.current,args.artifacts)
    except (OSError,ValueError,sqlite3.Error):
        print(json.dumps({'status':'verification_unavailable'}));raise SystemExit(2)
    print(json.dumps(report,sort_keys=True,indent=2))
    if not report['unchanged']:raise SystemExit(1)
