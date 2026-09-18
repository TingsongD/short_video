"""PL-04/PL-22: durable metric checkpoints — delayed jobs, honest
late/missed labels, auto-scheduling on confirmed public transitions."""
import json
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from modules.factory.domain.records import (
    Authorization, MetricSnapshot)
from modules.factory.integrations.publisher import UploadPostPublisher
from modules.factory.publishing.service import PublishingService
from modules.factory.scheduler.scheduler import Scheduler
from modules.factory.services.checkpoints import (
    CheckpointService, HORIZON_HOURS)
from modules.factory.services.commands import CommandQueue
from modules.factory.store import Database
from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
from modules.factory.testing.fakes import FakePublisher

NOW = "2026-09-17T12:00:00+00:00"
PUBLISHED = "2026-09-17T10:00:00+00:00"
SHA = hashlib.sha256(b'v').hexdigest()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _queue(db):
    return CommandQueue(db, Scheduler(db))


class _StubReadback:
    def __init__(self, observed_at):
        self.observed_at = observed_at
        self.calls = []

    def collect(self, publication_id, horizon, now=""):
        self.calls.append((publication_id, horizon))
        return MetricSnapshot(
            schema_version="metric_snapshot.v1",
            id=f"snap-{publication_id}-{horizon}", created_at=now,
            publication_id=publication_id, horizon=horizon,
            query_version="f32.v2", source="stub",
            observed_at=self.observed_at, metrics={"views": 100},
            availability={"views": "ok"})


def _public_pub(pid="pub-1", published_at=PUBLISHED):
    return {"id": pid, "status": "public",
            "published_at": published_at,
            "experiment_id": "exp-1", "experiment_revision": 1,
            "platform": "youtube"}


def _jobs(db):
    return [dict(r) for r in db.conn.execute(
        "SELECT * FROM jobs ORDER BY id").fetchall()]


# ---------------------------------------------------- scheduling --

def test_schedule_for_enqueues_delayed_jobs_per_horizon(db):
    svc = CheckpointService(db, _queue(db))
    out = svc.schedule_for(_public_pub(), now=NOW)
    assert {o["horizon"] for o in out} == set(HORIZON_HOURS)
    jobs = {j["id"]: j for j in _jobs(db)}
    assert len(jobs) == 5
    for o in out:
        job = jobs[o["job_id"]]
        expected = (datetime.fromisoformat(PUBLISHED) +
                    timedelta(hours=HORIZON_HOURS[o["horizon"]]))
        assert job["next_attempt_at"] == expected.isoformat()
        assert job["phase"] == "collect"


def test_schedule_is_idempotent_by_command_identity(db):
    svc = CheckpointService(db, _queue(db))
    svc.schedule_for(_public_pub(), now=NOW)
    again = svc.schedule_for(_public_pub(), now=NOW)
    assert len(again) == 5
    assert len(_jobs(db)) == 5        # no duplicate delayed jobs


def test_schedule_requires_confirmed_public_with_time_evidence(db):
    svc = CheckpointService(db, _queue(db))
    assert svc.schedule_for({"id": "p", "status": "scheduled",
                             "published_at": PUBLISHED}) == []
    assert svc.schedule_for({"id": "p", "status": "public",
                             "published_at": ""}) == []


def test_due_job_is_not_claimable_early(db):
    sched = Scheduler(db)
    svc = CheckpointService(db, CommandQueue(db, sched))
    svc.schedule_for(_public_pub(), now=NOW)
    # Scheduler clock is real-now: every due instant is in the past for
    # a 2026-09-17 publish only when the fake clock says so — override:
    sched.clock = lambda: datetime(2026, 9, 17, 11, 0,
                                   tzinfo=timezone.utc)
    assert sched.claim('collect') is None     # 24h not yet reached
    sched.clock = lambda: datetime(2026, 9, 18, 11, 0,
                                   tzinfo=timezone.utc)
    job = sched.claim('collect')
    assert job is not None
    assert job["id"] == "readback:pub-1:24h"


# ---------------------------------------------------- collection --

def test_collect_marks_schedule_collected_or_late(db):
    svc = CheckpointService(
        db, _queue(db),
        _StubReadback("2026-09-18T09:00:00+00:00"))
    svc.schedule_for(_public_pub(), now=NOW)
    svc.collect("pub-1", "24h", now="2026-09-18T09:30:00+00:00")
    # A second service whose observation lands after the 48h due:
    late_svc = CheckpointService(
        db, _queue(db),
        _StubReadback("2026-09-19T12:00:00+00:00"))
    late_svc.collect("pub-1", "48h", now="2026-09-19T12:00:00+00:00")
    states = {s["horizon"]: s["status"]
              for s in svc.for_publication("pub-1")}
    assert states["24h"] == "collected"    # observed before due
    assert states["48h"] == "late"         # observed, but past due
    assert states["72h"] in ("pending", "due")


def test_for_publication_marks_due_honestly(db):
    svc = CheckpointService(db, _queue(db))
    svc.schedule_for(_public_pub(), now=NOW)
    states = {s["horizon"]: s["status"]
              for s in svc.for_publication(
                  "pub-1", now="2026-09-18T11:00:00+00:00")}
    assert states["24h"] == "due"
    assert states["48h"] == "pending"


# ------------------------------------------- auto on public -------

def _auth(db):
    with db.uow() as u:
        u.records.put(Authorization(
            schema_version="authorization.v1", id="auth-1",
            created_at=NOW, scope_hash="sc",
            publication_authorized=True, status="authorized"))


def test_public_transition_auto_schedules_checkpoints(db, tmp_path):
    pub = FakePublisher()
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=pub.transport,
                                  verifier=pub.verify_post)
    commands = _queue(db)
    svc = PublishingService(
        db, publisher=adapter,
        effects=FixtureEffects(db, Executor(db)),
        accounts={"youtube:acct-main": "acct-main"}, max_per_day=20)
    chk = CheckpointService(db, commands)
    svc.on_public = chk.schedule_for
    _auth(db)
    svc.plan("pub-1", variant_plan_id="vp-1", final_sha256=SHA,
             platform="youtube", account_id="acct-main",
             metadata={"title": "T"}, authorization_id="auth-1")
    intent = json.loads(db.uow().records.get(
        'publicationintent', 'intent:pub-1')['body'])
    from modules.factory.execution.effects import EffectService
    auth = Authorization(
        schema_version='authorization.v1', id='approve:pub-1',
        created_at=NOW, scope_hash=intent['plan_hash'],
        status='authorized', publication_authorized=True,
        allowed_providers=['upload_post'],
        allowed_models={'upload_post': ['upload']},
        valid_until=(datetime.now(timezone.utc) +
                     timedelta(hours=1)).isoformat(),
        authorizing_action='fixture operator')
    EffectService(db).approve(
        auth, 'publicationintent', intent['id'],
        [dict(key='publish', kind='publication', provider='upload_post',
              model='upload', account='acct-main',
              request=intent['request'])], [])
    svc.authorize("pub-1", auth.id)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    svc.reconcile("pub-1")
    svc.reconcile("pub-1")             # advance steps to public
    p = svc.get("pub-1")
    assert p["status"] == "public"
    schedules = chk.for_publication("pub-1")
    assert {s["horizon"] for s in schedules} == set(HORIZON_HOURS)
    assert all(s["job_id"] for s in schedules)
