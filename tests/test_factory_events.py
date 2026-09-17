"""F08 — event replay, cursors, retention, timing, redaction, health."""
import json

import pytest

from modules.factory.domain import ContractError, Job
from modules.factory.events import (EventSubscription, ResyncRequired,
                                    health_report, redact, timeline)
from modules.factory.events.subscriptions import EventSubscription
from modules.factory.execution import Executor
from modules.factory.scheduler import Scheduler
from modules.factory.store import Database
from modules.factory.testing.clock import FakeClock
from modules.factory.testing.fakes import FakeProvider
from modules.factory.testing.ids import IdFactory

NOW = "2026-09-16T12:00:00Z"


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    ids = IdFactory(tmp_path / "ids.json")
    provider = FakeProvider("v", tmp_path / "remote", ids, FakeClock())
    yield db, provider
    db.close()


def _job(db, jid="j1", status="ready"):
    with db.uow() as u:
        u.jobs.put(Job(schema_version="job.v1", id=jid, created_at=NOW,
                       logical_key=f"lk-{jid}", phase="p", status=status))
        u.events.append(f"job:{jid}", "planned", {})


class TestReplayAndCursor:
    def test_replay_from_cursor(self, env):
        db, _ = env
        _job(db)
        sub = EventSubscription(db)
        evs = sub.replay("job:j1")
        assert [e["type"] for e in evs] == ["planned"]
        cursor = evs[-1]["seq"]
        with db.uow() as u:
            u.events.append("job:j1", "claimed", {"worker": "w"})
        more = sub.replay("job:j1", cursor)
        assert [e["type"] for e in more] == ["claimed"]

    def test_retention_forces_resync(self, env):
        db, _ = env
        _job(db)
        with db.uow() as u:
            for i in range(10):
                u.events.append("job:j1", f"step{i}", {})
        sub = EventSubscription(db)
        dropped = sub.retain("job:j1", keep_last_n=3)
        assert dropped == 8
        with pytest.raises(ResyncRequired) as e:
            sub.replay("job:j1", cursor=1)
        assert "resync" in str(e.value)
        snap = sub.snapshot("job:j1")
        assert snap["projection"]["status"] == "ready"
        assert snap["cursor"] > 0

    def test_event_ids_monotonic_in_txn(self, env):
        db, _ = env
        with db.uow() as u:
            a = u.events.append("s", "a", {})
            b = u.events.append("s", "b", {})
            c = u.events.append("s", "c", {})
        assert a < b < c


class TestTiming:
    def test_derived_durations(self):
        events = [
            {"type": "planned", "created_at": "2026-09-16T10:00:00Z"},
            {"type": "claimed", "created_at": "2026-09-16T10:02:00Z"},
            {"type": "dispatch_started",
             "created_at": "2026-09-16T10:02:05Z"},
            {"type": "accepted", "created_at": "2026-09-16T10:02:10Z"},
            {"type": "provider_finished",
             "created_at": "2026-09-16T10:04:00Z",
             "body": {"provider_finished_at": "2026-09-16T10:03:50Z"}},
            {"type": "downloaded", "created_at": "2026-09-16T10:04:30Z"},
        ]
        t = timeline(events)
        d = t["durations"]
        assert d["queue_wait_s"] == 120.0
        assert d["provider_elapsed_s"] == pytest.approx(100.0)
        assert d["collection_delay_s"] == 30.0
        assert d["wall_clock_s"] == 270.0

    def test_no_fabricated_provider_finish(self):
        events = [
            {"type": "accepted", "created_at": "2026-09-16T10:00:00Z"},
            {"type": "provider_finished",
             "created_at": "2026-09-16T10:05:00Z", "body": {}},
        ]
        t = timeline(events)
        assert t["uncertainty"] and "did not report" in t["uncertainty"][0]
        assert t["durations"]["provider_elapsed_s"] == 300.0

    def test_missing_stages_are_null(self):
        t = timeline([{"type": "planned",
                       "created_at": "2026-09-16T10:00:00Z"}])
        assert t["durations"]["provider_elapsed_s"] is None
        assert t["durations"]["render_s"] is None


class TestRedaction:
    def test_secret_shapes_removed(self):
        doc = {"err": "Bearer abcdefghijklmnopqrstuvwxyz0123456789",
               "url": "https://x/y?sig=0123456789abcdef&Expires=999",
               "oauth": "ya29.abcdefghij0123456789",
               "nested": {"code": "abc123def456"}}
        out = json.dumps(redact(doc))
        assert "abcdefghijklmnop" not in out
        assert "sig=0123" not in out
        assert "[redacted]" in out
        assert out.count("[redacted]") >= 3

    def test_safe_refs_preserved(self):
        doc = {"artifact": "art:abc123", "receipt": "rcpt:9"}
        assert redact(doc) == doc


class TestHealth:
    def test_stale_lease_and_unknown_attempt(self, env):
        db, provider = env
        _job(db, "j-lease")
        db.conn.execute(
            "UPDATE jobs SET lease_owner='w1', "
            "lease_expires='2000-01-01', status='running' WHERE id='j-lease'")
        ex = Executor(db, provider)
        aid = ex.prepare("j-lease", 1, {"p": 1})
        ex._set_status(aid, "unknown", "drill")
        rep = health_report(db, now="2026-09-16T13:00:00Z")
        kinds = {s["signal"] for s in rep["signals"]}
        assert "stale_lease" in kinds and "unknown_attempt" in kinds
        stale = next(s for s in rep["signals"] if s["signal"] == "stale_lease")
        assert stale["owner"] == "w1"
        unk = next(s for s in rep["signals"]
                   if s["signal"] == "unknown_attempt")
        assert "resolve_unknown" in unk["action"]

    def test_prolonged_ready(self, env):
        db, _ = env
        _job(db, "old-ready")   # created_at = NOW (12:00), now=+3h
        rep = health_report(db, now="2026-09-16T15:00:00Z",
                            stale_ready_s=60)
        assert any(s["signal"] == "prolonged_ready"
                   for s in rep["signals"])

    def test_clean_report(self, env):
        db, _ = env
        rep = health_report(db, min_free_bytes=0)
        assert rep["ok"]
