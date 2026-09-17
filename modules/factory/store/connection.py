"""Connection management: WAL, foreign keys, bounded busy handling,
forward-compatibility refusal."""
import sqlite3

from ..domain.errors import ContractError
from . import schema as _schema

BUSY_MS = 5000


class NewerDatabaseError(ContractError):
    def __init__(self, found):
        super().__init__("newer_database", "schema_version",
                         f"db is v{found}, binary knows v{_schema.CURRENT_VERSION}")


def _configure(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def current_version(conn):
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def migrate(conn):
    v = current_version(conn)
    if v > _schema.CURRENT_VERSION:
        raise NewerDatabaseError(v)
    for num, ddl in _schema.MIGRATIONS:
        if num > v:
            # executescript commits pending transactions; the transaction must
            # be part of the script so DDL and its version advance atomically.
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + ddl +
                    "\nINSERT OR REPLACE INTO meta(key,value) VALUES"
                    f"('schema_version','{int(num)}');\nCOMMIT;")
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise
    return _schema.CURRENT_VERSION


def open(path, readonly=False):
    """Open (and migrate if needed) a factory database."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        v = current_version(conn)
        if v > _schema.CURRENT_VERSION:
            conn.close()
            raise NewerDatabaseError(v)
        return conn
    conn = _configure(sqlite3.connect(path, isolation_level=None,
                                      check_same_thread=False))
    migrate(conn)
    return conn
