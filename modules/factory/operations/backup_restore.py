"""Backup/restore (F30): consistent DB + ledger + artifact manifest +
receipts in one manifest, hash-verified restore into a NEW root, and
a reconciliation gate before restored state can dispatch.

Git history is not the backup for ignored financial state — the
preserved legacy ledger and unresolved authority/receipt records ship
inside every backup manifest.
"""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..domain.errors import ContractError
from ..store import backup as store_backup


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_backup(db, workspace, dest_dir, ledger_paths=()):
    """→ manifest. Consistent: sqlite online backup (WAL-safe) +
    referenced files hashed into one manifest."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    db_file = dest / "factory.db"
    db.backup_to(db_file)
    files = {"factory.db": _sha(db_file)}
    # artifact manifest — registry rows, not the media itself
    arts = dest / "artifacts-manifest.json"
    rows = db.uow().conn.execute(
        "SELECT id,sha256,status,local_path FROM artifacts").fetchall()
    arts.write_text(json.dumps(
        [{"id": a["id"], "sha256": a["sha256"], "status": a["status"],
          "local_path": a["local_path"]} for a in rows], indent=1))
    files["artifacts-manifest.json"] = _sha(arts)
    # unresolved intents + financial records (ledger is git-ignored)
    fin = dest / "financial-state.json"
    intents = db.uow().conn.execute(
        "SELECT intent_key,kind,status,remote_id FROM intents"
    ).fetchall()
    budgets = db.uow().conn.execute(
        "SELECT id,body FROM records WHERE kind='budget'").fetchall()
    fin.write_text(json.dumps(
        {"unresolved_intents": [dict(i) for i in intents],
         "budgets": [json.loads(b["body"]) for _, b in budgets]},
        indent=1))
    files["financial-state.json"] = _sha(fin)
    for lp in ledger_paths:
        lp = Path(lp)
        if lp.exists():
            tgt = dest / lp.name
            shutil.copy2(lp, tgt)
            files[lp.name] = _sha(tgt)
    manifest = {"created_at": _now(), "files": files,
                "db_integrity": store_backup.verify(db_file)}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def restore_into(backup_dir, new_root):
    """Restore into a FRESH root: verify manifest hashes + DB
    integrity; the original workspace is untouched. Returns the
    restored layout — dispatch stays gated until reconcile."""
    backup_dir, new_root = Path(backup_dir), Path(new_root)
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    if new_root.exists() and any(new_root.iterdir()):
        raise ContractError("restore_target_exists", "new_root",
                            str(new_root))
    new_root.mkdir(parents=True, exist_ok=True)
    problems = []
    for name, expect in manifest["files"].items():
        src = backup_dir / name
        if not src.exists():
            problems.append(f"missing:{name}")
            continue
        if _sha(src) != expect:
            problems.append(f"hash_mismatch:{name}")
            continue
        shutil.copy2(src, new_root / name)
    if problems:
        raise ContractError("restore_corrupt", "files",
                            ";".join(problems))
    integrity = store_backup.verify(new_root / "factory.db")
    return {"restored": str(new_root), "integrity": integrity,
            "dispatch": "gated — reconcile external effects first",
            "at": _now()}
