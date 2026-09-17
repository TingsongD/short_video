"""Backup/restore with integrity verification. Uses the SQLite online
backup API (safe on live WAL databases); restores verify integrity_check
and schema_version before declaring success."""
import os
import sqlite3

from ..domain.errors import ContractError
from . import connection


def backup(db_path, dest_path):
    src = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(dest_path))
    try:
        src.backup(dest)
    finally:
        src.close()
        dest.close()
    return verify(dest_path)


def verify(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ContractError("restore_corrupt", "integrity_check",
                                integrity)
        version = connection.current_version(conn)
        return {"integrity": integrity, "schema_version": version}
    finally:
        conn.close()


def restore(db_path, dest_path):
    """Restore a backup file into a new location. Never overwrites an
    existing file — restore into a fresh path, then reconcile external
    effects before pointing the app at it (handover §16.2)."""
    if os.path.exists(dest_path):
        raise ContractError("restore_target_exists", "dest_path",
                            str(dest_path))
    src = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(dest_path))
    try:
        src.backup(dest)
    finally:
        src.close()
        dest.close()
    return verify(dest_path)
