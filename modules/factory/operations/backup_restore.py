"""Self-contained, verified backup and fresh-root restore.

Restoration never grants authority: its persistent activation hold must be
resolved with evidence about effects occurring after the snapshot.
"""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..domain.errors import ContractError
from ..store import Database, backup as store_backup
from .paths import database_path


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ContractError('backup_path_escape', 'path', name)
    return path


def create_backup(db, workspace, dest_dir, ledger_paths=()):
    dest, workspace = Path(dest_dir), Path(workspace)
    if dest.exists() and any(dest.iterdir()):
        raise ContractError('backup_target_exists', 'dest')
    dest.mkdir(parents=True, exist_ok=True)
    db.backup_to(dest / 'factory.db')
    snapshot = sqlite3.connect(f'file:{dest / "factory.db"}?mode=ro', uri=True)
    snapshot.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in snapshot.execute('SELECT * FROM artifacts')]
        root = snapshot.execute("SELECT value FROM meta WHERE key='artifact_root'").fetchone()
        source_root = Path(root[0]) if root else database_path(workspace).parent / 'artifacts'
        arts = []
        for row in rows:
            if not row['local_path'] or not row['sha256']:
                raise ContractError('backup_missing_artifact', 'artifact', row['id'])
            src = _inside(source_root, row['local_path'])
            if not src.is_file() or _sha(src) != row['sha256']:
                raise ContractError('backup_missing_artifact', 'artifact', row['id'])
            rel = 'media/' + row['local_path']
            target = _inside(dest, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            arts.append({k: row[k] for k in ('id','sha256','status','local_path')})
        (dest / 'artifacts-manifest.json').write_text(json.dumps(arts, indent=2))
        financial = {table: [dict(r) for r in snapshot.execute(f'SELECT * FROM {table}')]
                     for table in ('budgets','reservations','reservation_lines','ledger_imports')}
        financial['unresolved_intents'] = [dict(r) for r in snapshot.execute('SELECT * FROM intents')]
        (dest / 'financial-state.json').write_text(json.dumps(financial, indent=2))
    finally:
        snapshot.close()
    ledgers = list(map(Path, ledger_paths))
    legacy = workspace / 'data/costs/ledger.json'
    if legacy.exists() and legacy not in ledgers:
        ledgers.append(legacy)
    destinations = {}
    for source in ledgers:
        if not source.is_file():
            raise ContractError('backup_missing_ledger', 'ledger', str(source))
        name = source.name
        if name in destinations:
            raise ContractError('backup_ledger_collision', 'ledger', name)
        shutil.copy2(source, dest / name)
        destinations[name] = 'data/costs/' + name
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                'files': {str(p.relative_to(dest)): _sha(p) for p in dest.rglob('*') if p.is_file()},
                'ledgers': destinations, 'db_integrity': store_backup.verify(dest / 'factory.db')}
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def restore_into(backup_dir, new_root):
    backup_dir, new_root = Path(backup_dir), Path(new_root)
    manifest = json.loads((backup_dir / 'manifest.json').read_text())
    if new_root.exists() and any(new_root.iterdir()):
        raise ContractError('restore_target_exists', 'new_root', str(new_root))
    required = {'factory.db','artifacts-manifest.json','financial-state.json'}
    if not required.issubset(manifest['files']):
        raise ContractError('restore_corrupt', 'files', 'missing required manifest entries')
    for name, expected in manifest['files'].items():
        src = _inside(backup_dir, name)
        if not src.is_file() or _sha(src) != expected:
            raise ContractError('restore_corrupt', 'files', name)
    # Restore uses a fixed fresh workspace layout; no inherited environment
    # override may redirect these writes into an existing production root.
    target_db = new_root / 'data/factory/factory.db'
    for name in manifest['files']:
        if name == 'factory.db':
            target = target_db
        elif name.startswith('media/'):
            target = _inside(new_root / 'data/factory/artifacts', name[6:])
        elif name in manifest.get('ledgers', {}):
            target = _inside(new_root, manifest['ledgers'][name])
        else:
            target = _inside(new_root / 'data/factory/restore-evidence', name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_inside(backup_dir, name), target)
    db = Database(target_db)
    with db.uow() as u:
        u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('artifact_root',?)",
                       (str((new_root / 'data/factory/artifacts').resolve()),))
        u.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('restore_pending',?)",
                       (manifest['created_at'],))
        u.events.append('factory:restore', 'restored_blocked', {'backup_at': manifest['created_at']})
    db.close()
    return {'restored': str(new_root), 'database': str(target_db),
            'integrity': store_backup.verify(target_db),
            'dispatch': 'gated — reconcile external effects first'}
