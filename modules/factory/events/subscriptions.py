"""Event replay from a durable cursor, gap detection, retention and
snapshot resynchronization (F08 checklist 5).

Events are monotonically numbered in the same transaction as the state
change. A subscriber holds a cursor = last seen seq. If the cursor fell
behind the retained window, replay returns an explicit resync route —
never silently skips.
"""
from ..domain.records import canonical
from ..store.uow import utcnow
from .redact import redact


class ResyncRequired(Exception):
    def __init__(self, stream, min_seq, snapshot_seq):
        self.stream, self.min_seq = stream, min_seq
        self.snapshot_seq = snapshot_seq
        super().__init__(
            f"cursor expired for {stream}: earliest retained seq "
            f"{min_seq}; resync via snapshot at {snapshot_seq}")


class EventSubscription:
    def __init__(self, db):
        self.db = db

    def replay(self, stream, cursor=0):
        """Events after cursor. If the cursor is below the retained
        window the caller must resync via snapshot() instead."""
        min_seq = self._min_seq(stream)
        if cursor and cursor < min_seq - 1:
            raise ResyncRequired(stream, min_seq,
                                 self._max_seq(stream))
        return self.db.uow().events.since(stream, cursor)

    def replay_all(self, cursor=0):
        rows = self.db.conn.execute(
            "SELECT * FROM events WHERE seq>? ORDER BY seq",
            (cursor,)).fetchall()
        return [dict(r) for r in rows]

    def _min_seq(self, stream):
        row = self.db.conn.execute(
            "SELECT MIN(seq) FROM events WHERE stream=?", (stream,)
        ).fetchone()
        return row[0] or 0

    def _max_seq(self, stream):
        row = self.db.conn.execute(
            "SELECT MAX(seq) FROM events WHERE stream=?", (stream,)
        ).fetchone()
        return row[0] or 0

    def snapshot(self, stream):
        """Resync route: latest durable projection for the stream + the
        event high-water mark to continue replaying from."""
        kind = stream.split(":", 1)[0]
        body = {}
        if kind == "job":
            jid = stream.split(":", 1)[1]
            row = self.db.uow().jobs.get(jid)
            body = dict(row) if row else {}
        elif kind == "attempt":
            aid = stream.split(":", 1)[1]
            row = self.db.conn.execute(
                "SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
            body = dict(row) if row else {}
        elif kind == "experiment":
            eid = stream.split(":", 1)[1]
            row = self.db.conn.execute(
                "SELECT * FROM records WHERE id=? ORDER BY revision DESC "
                "LIMIT 1", (eid,)).fetchone()
            body = dict(row) if row else {}
        return {"stream": stream, "projection": redact(body),
                "cursor": self._max_seq(stream), "kind": kind}

    def retain(self, stream, keep_last_n):
        """Retention: drop events older than the newest N; a marker row
        records the trim so a gap is explainable, not silent."""
        rows = self.db.conn.execute(
            "SELECT seq FROM events WHERE stream=? ORDER BY seq DESC",
            (stream,)).fetchall()
        if len(rows) <= keep_last_n:
            return 0
        drop = [r["seq"] for r in rows[keep_last_n:]]
        with self.db.uow() as u:
            for seq in drop:
                u.conn.execute(
                    "DELETE FROM events WHERE stream=? AND seq=?",
                    (stream, seq))
            u.conn.execute(
                "INSERT INTO events(stream,type,body,created_at) "
                "VALUES(?,?,?,?)",
                (stream, "retention_marker",
                 canonical({"dropped_before": max(drop) + 1,
                            "kept": keep_last_n}), utcnow()))
        return len(drop)
