"""Durable metric-checkpoint scheduling (PL-04).

When a publication reaches a provider-confirmed public state with
usable published-at evidence, one readback job per horizon is enqueued
with a durable `not_before` due instant. No lease is held while
waiting; a sleeping laptop simply claims the job late, and the
schedule record marks that lateness honestly instead of fabricating
a punctual observation."""
import json
from datetime import datetime, timedelta, timezone

from ..domain.errors import ContractError
from ..domain.records import CheckpointSchedule
from ..store.uow import utcnow

HORIZON_HOURS = {"24h": 24, "48h": 48, "72h": 72, "7d": 168, "28d": 672}
# §8.2: complete-reporting-day windows join the same durable schedule
# when the platform has a qualified source-calendar route.
COMPLETE_DAY_HORIZONS = {"7d_complete": 7, "28d_complete": 28}
# Bounded retry for unprocessed/partial readbacks — the schedule
# records attempts; a snapshot that never becomes complete exhausts
# to 'failed' rather than polling forever.
RETRYABLE = {"pending", "partial", "failed"}
MAX_ATTEMPTS = 6


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _parse(at):
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


class CheckpointService:
    def __init__(self, db, commands, readback=None):
        """readback may be the service itself or a zero-arg getter —
        a late-bound lookup keeps an operator-swapped readback live."""
        self.db, self.commands = db, commands
        self._readback = readback

    @property
    def readback(self):
        rb = self._readback
        return rb() if callable(rb) else rb

    @readback.setter
    def readback(self, value):
        self._readback = value

    # --------------------------------------------------- scheduling --

    def schedule_for(self, publication, now=""):
        """Enqueue one delayed readback per horizon for a confirmed
        public destination. Idempotent by command identity — a second
        call for the same publication returns the existing jobs."""
        now = now or utcnow()
        p = (publication.to_dict() if hasattr(publication, "to_dict")
             else dict(publication))
        if p.get("status") != "public" or not p.get("published_at"):
            return []
        published = _parse(p["published_at"])
        entries = [(h, _iso(published + timedelta(hours=hours)))
                   for h, hours in HORIZON_HOURS.items()]
        rb = self.readback
        cap = getattr(rb, "window_capability", None)
        if cap is not None and cap(
                p.get("platform", "youtube"),
                "source_calendar_window") is not None:
            # Due instants come from the readback window itself — the
            # source-day calendar, not a fixed hour offset.
            for name in COMPLETE_DAY_HORIZONS:
                try:
                    _, _, due_at, _ = rb._window_for(
                        p, name, published)
                except Exception:
                    continue
                entries.append((name, _iso(due_at)))
        out = []
        for horizon, due in entries:
            sid = f"chk-{p['id']}-{horizon}"
            existing = self.db.uow().records.get(
                "checkpointschedule", sid)
            if existing is None:
                rec = CheckpointSchedule(
                    schema_version="checkpoint_schedule.v1", id=sid,
                    created_at=now, publication_id=p["id"],
                    horizon=horizon, due_at=due, status="pending")
                with self.db.uow() as u:
                    u.records.put(rec)
            job = self.commands.enqueue(
                "readback",
                {"publication_id": p["id"], "horizon": horizon},
                identity=f"readback:{p['id']}:{horizon}",
                phase="collect",
                experiment_id=p.get("experiment_id", ""),
                revision=p.get("experiment_revision", 0),
                not_before=due)
            self._set(sid, job_id=job["job_id"],
                      status="due" if due <= now else "pending")
            out.append({"schedule_id": sid, "horizon": horizon,
                        "due_at": due, "job_id": job["job_id"]})
        return out

    # --------------------------------------------------- collection --

    def collect(self, publication_id, horizon, now=""):
        """Worker entry: collect the snapshot, then stamp the schedule
        with the honest outcome — 'collected' on time, 'late' when the
        observation landed after its due instant."""
        if self.readback is None:
            raise ContractError("readback_unavailable", "publication_id",
                                publication_id)
        # The readback service owns the observation clock — never pass
        # wall-clock now over an operator/injected clock.
        snap = (self.readback.collect(publication_id, horizon, now=now)
                if now else
                self.readback.collect(publication_id, horizon))
        sid = f"chk-{publication_id}-{horizon}"
        row = self.db.uow().records.get("checkpointschedule", sid)
        if row is not None:
            sched = json.loads(row["body"])
            attempts = sched.get("attempts", 0) + 1
            comp = getattr(snap, "completeness", "") or ""
            if comp in RETRYABLE:
                # Not yet usable evidence — the checkpoint stays open
                # for a bounded retry; exhaustion is a real failure,
                # never a quiet success (§8.2 retry-until-processed).
                status = ("retrying" if attempts < MAX_ATTEMPTS
                          else "failed")
            else:
                late = (sched.get("due_at") and
                        _parse(snap.observed_at) >
                        _parse(sched["due_at"]))
                status = "late" if late else "collected"
            self._set(sid, status=status, attempts=attempts,
                      query_version=getattr(snap, "query_version", ""))
        return snap

    def seconds_until_due(self, publication_id, horizon):
        """Seconds until the observation clock reaches this horizon.

        A scheduler clock that is ahead of the readback clock can claim
        the job early; the worker defers by this amount instead of
        failing a horizon that is honestly not due yet.
        """
        sid = f"chk-{publication_id}-{horizon}"
        row = self.db.uow().records.get("checkpointschedule", sid)
        if row is None:
            return 60.0
        due = _parse(json.loads(row["body"])["due_at"])
        rb = self.readback
        clock = getattr(rb, "clock", None)
        if callable(clock):
            now = clock()
        else:
            now = datetime.now(timezone.utc)
        if isinstance(now, str):
            now = _parse(now)
        return max(1.0, (due - now).total_seconds())

    def next_delay(self, publication_id, horizon):
        """(defer_seconds, status) for a checkpoint after a collect —
        'retrying' yields a bounded backoff for the worker to defer
        with; anything else means the schedule reached a terminal
        label."""
        sid = f"chk-{publication_id}-{horizon}"
        row = self.db.uow().records.get("checkpointschedule", sid)
        if row is None:
            return None, ""
        sched = json.loads(row["body"])
        if sched.get("status") != "retrying":
            return None, sched.get("status", "")
        attempts = sched.get("attempts", 1)
        return min(60 * 2 ** max(attempts - 1, 0), 3600), "retrying"

    def fail(self, publication_id, horizon, now=""):
        sid = f"chk-{publication_id}-{horizon}"
        row = self.db.uow().records.get("checkpointschedule", sid)
        if row is not None:
            sched = json.loads(row["body"])
            self._set(sid, status="failed",
                      attempts=sched.get("attempts", 0) + 1)

    # ------------------------------------------------------- status --

    def for_publication(self, publication_id, now=""):
        """Schedules with honest labels: a past-due pending entry is
        'due'; one that can never be satisfied (no snapshot, due long
        past) is 'missed'. Missing evidence is never reported as zero."""
        now = now or utcnow()
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='checkpointschedule'"
            " AND json_extract(body,'$.publication_id')=?"
            " ORDER BY id", (publication_id,)).fetchall()
        out = []
        for r in rows:
            s = json.loads(r[0])
            if s["status"] in ("pending", "due") and s.get("due_at"):
                if s["due_at"] <= now:
                    s["status"] = "due"
            out.append(s)
        return out

    def mark_missed(self, publication_id, horizon):
        sid = f"chk-{publication_id}-{horizon}"
        self._set(sid, status="missed")

    def _set(self, sid, **fields):
        with self.db.uow() as u:
            row = u.records.get("checkpointschedule", sid)
            if row is None:
                return
            body = json.loads(row["body"])
            body.update(fields)
            u.conn.execute(
                "UPDATE records SET body=?,updated_at=? WHERE kind="
                "'checkpointschedule' AND id=?",
                (json.dumps(body), utcnow(), sid))
