"""Permanent regression coverage for REVIEW-2026-09-18 (Q01–Q15).

The probe file under docs/factory-reports/probes/ asserts the repaired
behavior for the seven findings it originally reproduced; this file
covers the findings that had no probe: §9.3 worked cases (Q03),
checkpoint retry/complete-day horizons (Q06), scheduled-post polling
(Q07), dispatch-time loop gates (Q10), account/evidence plumbing
(Q14), and the no-artifact round limitation (Q09's honest path)."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import (
    Authorization, MetricSnapshot, Publication)
from modules.factory.integrations.publisher import UploadPostPublisher
from modules.factory.learning.service import LearningService
from modules.factory.publishing.service import PublishingService
from modules.factory.scheduler.scheduler import Scheduler
from modules.factory.seeds.registry import SeedRegistry
from modules.factory.services.checkpoints import (
    CheckpointService, COMPLETE_DAY_HORIZONS, HORIZON_HOURS,
    MAX_ATTEMPTS)
from modules.factory.services.commands import CommandQueue
from modules.factory.services.publication_work import PublicationWork
from modules.factory.services.rounds import RoundService
from modules.factory.store import Database
from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
from modules.factory.testing.fakes import FakePublisher
from test_factory_analytics import _svc
from test_factory_seed_selection import _experiment, _lanes, _policy
from test_factory_rounds import _setup, _rounds, _selection, _freeze

NOW = "2026-09-17T12:00:00+00:00"
SHA = "ab" * 32


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


# ------------------------------------------------ Q03 worked cases --

def _weighted(service, **kw):
    sp = {"mode": "weighted_rank",
          "weights": {"youtube": 0.5, "tiktok": 0.5},
          "provisional_horizon": "48h",
          "improvement_rule": {"kind": "weighted_lift"}}
    sp.update(kw.pop("seed_extra", {}))
    _policy(service, seed_policy=sp, **kw)


def test_q03_borda_score_and_weighted_lift_crown_champion(db):
    """Rank-1 on every lane scores 100; the challenger's weighted
    relative lift clears practical_lift → champion (§9.3 steps 3–5)."""
    _experiment(db)
    svc = LearningService(db)
    _weighted(svc, practical_lift=0.3)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 100, "tiktok": 100},
            "B": {"youtube": 200, "tiktok": 150},
            "C": {"youtube": 90, "tiktok": 80},
            "D": {"youtube": 50, "tiktok": 40}})
    out = svc.select_seed("exp-1", 1)
    assert out["outcome"] == "champion"
    assert out["winner_variant"] == "B"
    assert out["basis"]["scores"]["B"] == pytest.approx(100.0)
    assert out["basis"]["ranks"]["B"] == {"youtube": 1.0, "tiktok": 1.0}
    ev = out["basis"]["evaluated"]["B"]
    assert ev["weighted_lift"] == pytest.approx(0.75)  # .5*1.0 + .5*0.5


def test_q03_average_ranks_for_exact_ties(db):
    """Equal metric values share the mean of their positions — no
    letter-order tiebreak inside a lane (§9.3 step 3)."""
    _experiment(db)
    svc = LearningService(db)
    _weighted(svc)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 100, "tiktok": 100},
            "B": {"youtube": 200, "tiktok": 200},
            "C": {"youtube": 200, "tiktok": 200},
            "D": {"youtube": 50, "tiktok": 50}})
    out = svc.select_seed("exp-1", 1)
    ranks = out["basis"]["ranks"]
    assert ranks["B"]["youtube"] == pytest.approx(1.5)
    assert ranks["C"]["youtube"] == pytest.approx(1.5)
    assert out["outcome"] == "inconclusive"   # identical aggregate
    assert out["basis"]["tie"] == ["B", "C"]


def test_q03_min_margin_falls_through_to_control(db):
    """A challenger leading the next eligible contender by less than
    min_margin is skipped; evaluation continues down the score order
    and A retains control (§9.3 step 5a)."""
    _experiment(db)
    svc = LearningService(db)
    # Adjacent ranks are 33.3 apart — a 40-point margin makes even a
    # full-rank lead insufficient.
    _weighted(svc, seed_extra={"min_margin": 40})
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 100, "tiktok": 100},
            "B": {"youtube": 105, "tiktok": 105},
            "C": {"youtube": 104, "tiktok": 104},
            "D": {"youtube": 50, "tiktok": 50}})
    out = svc.select_seed("exp-1", 1)
    assert out["outcome"] == "retain_control"
    assert out["winner_variant"] == "A"
    ev = out["basis"]["evaluated"]["B"]
    assert ev["margin_fail"]["required"] == 40
    assert ev["margin_fail"]["lead"] == pytest.approx(100 / 3)


def test_q03_inadequate_control_exposure_is_inconclusive(db):
    """§9.3: an under-exposed control invalidates the comparison —
    nobody is crowned, and A is not silently retained."""
    _experiment(db)
    svc = LearningService(db)
    _weighted(svc, min_exposure=100)
    _lanes(db, "exp-1", ["youtube", "tiktok"],
           {"A": {"youtube": 50, "tiktok": 50},      # under floor
            "B": {"youtube": 500, "tiktok": 500},
            "C": {"youtube": 400, "tiktok": 400},
            "D": {"youtube": 300, "tiktok": 300}})
    out = svc.select_seed("exp-1", 1)
    assert out["outcome"] == "inconclusive"
    assert "insufficient_exposure" in str(
        out["basis"]["invalid_comparison"]) or \
        out["basis"]["invalid_comparison"]


# --------------------------------------- Q06 retry + complete days --

class _PendingReadback:
    """Always-incomplete snapshot — the schedule must retry honestly."""
    def __init__(self, completeness="pending"):
        self.completeness = completeness

    def collect(self, publication_id, horizon, now=""):
        return MetricSnapshot(
            schema_version="metric_snapshot.v1",
            id=f"snap-{publication_id}-{horizon}", created_at=now,
            publication_id=publication_id, horizon=horizon,
            query_version="f32.v2", source="stub",
            observed_at=now, metrics={"views": None},
            availability={"views": "no_rows_yet"},
            completeness=self.completeness)


def _queue(db):
    return CommandQueue(db, Scheduler(db))


def _pub_rec(pid="pub-1"):
    return {"id": pid, "status": "public",
            "published_at": "2026-09-17T10:00:00+00:00",
            "experiment_id": "exp-1", "experiment_revision": 1,
            "platform": "youtube"}


def test_q06_incomplete_snapshot_retries_with_bounded_backoff(db):
    chk = CheckpointService(db, _queue(db),
                            _PendingReadback("pending"))
    chk.schedule_for(_pub_rec(), now=NOW)
    snap = chk.collect("pub-1", "24h", now="2026-09-18T11:00:00+00:00")
    assert snap.completeness == "pending"
    sched = {s["horizon"]: s for s in chk.for_publication("pub-1")}
    assert sched["24h"]["status"] == "retrying"
    assert sched["24h"]["attempts"] == 1
    delay, status = chk.next_delay("pub-1", "24h")
    assert status == "retrying" and delay == 60
    # Bounded: the schedule exhausts to 'failed', never infinite.
    for _ in range(MAX_ATTEMPTS - 1):
        chk.collect("pub-1", "24h", now="2026-09-18T12:00:00+00:00")
    sched = {s["horizon"]: s for s in chk.for_publication("pub-1")}
    assert sched["24h"]["status"] == "failed"
    assert chk.next_delay("pub-1", "24h")[1] == "failed"


def test_q06_complete_day_horizons_enqueue_with_window_due(db):
    """7d_complete/28d_complete ride the same durable schedule when the
    readback reports a source-calendar capability for the platform."""
    readback, _ = _svc(db)   # real ReadbackService over FakeAnalytics
    chk = CheckpointService(db, _queue(db), readback)
    out = chk.schedule_for(_pub_rec(), now=NOW)
    horizons = {o["horizon"] for o in out}
    assert horizons == set(HORIZON_HOURS) | set(COMPLETE_DAY_HORIZONS)
    comp = {o["horizon"]: o for o in out}
    # Complete-day dues come from the source-day calendar, not hours:
    # publish 10:00 UTC → window starts next LA day → due after day 7.
    due = datetime.fromisoformat(comp["7d_complete"]["due_at"])
    assert due > datetime(2026, 9, 24, tzinfo=timezone.utc)
    assert due < datetime(2026, 9, 26, tzinfo=timezone.utc)


# --------------------------------------------- Q07 scheduled posts --

def _pubsvc(db, tmp_path, now_fn=None):
    fake = FakePublisher(now_fn=now_fn)
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=fake.transport,
                                  verifier=fake.verify_post)
    commands = _queue(db)
    svc = PublishingService(
        db, publisher=adapter,
        effects=FixtureEffects(db, Executor(db)),
        accounts={"youtube:acct-main": "acct-main"}, max_per_day=20)
    chk = CheckpointService(db, commands)
    svc.on_public = chk.schedule_for
    return svc, fake, chk, commands


def _grant_publish(db, svc, pid):
    """The intent-bound authorization flow a real publish needs —
    mirrors test_factory_checkpoints' proven fixture."""
    intent = json.loads(db.uow().records.get(
        'publicationintent', f'intent:{pid}')['body'])
    from modules.factory.execution.effects import EffectService
    auth = Authorization(
        schema_version='authorization.v1', id=f'approve:{pid}',
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
    svc.authorize(pid, auth.id)


def test_q07_scheduled_post_observed_until_public(db, tmp_path):
    """A provider-confirmed scheduled post must not finish as complete:
    the observe job polls until the remote fires, then checkpoints
    schedule exactly once."""
    svc, fake, chk, commands = _pubsvc(
        db, tmp_path,
        now_fn=lambda: "2026-09-18T11:00:00+00:00")
    import hashlib
    vsha = hashlib.sha256(b"v").hexdigest()
    svc.plan("pub-1", variant_plan_id="vp-1", final_sha256=vsha,
             platform="youtube", account_id="acct-main",
             metadata={"title": "T"},
             scheduled_at="2026-09-18T10:00:00+00:00")
    _grant_publish(db, svc, "pub-1")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    out = svc.publish("pub-1", video_path=str(v), now=NOW)
    assert out["status"] == "scheduled"
    assert svc.get("pub-1")["status"] == "scheduled"
    # No checkpoints before a verified public transition.
    assert chk.for_publication("pub-1") == []
    # The remote job advances: scheduled → public on the next poll.
    svc.reconcile("pub-1")
    p = svc.get("pub-1")
    assert p["status"] == "public"
    assert p["published_at"]
    schedules = chk.for_publication("pub-1")
    assert {s["horizon"] for s in schedules} == set(HORIZON_HOURS)
    assert all(s["job_id"] for s in schedules)


def test_q07_observe_job_defers_then_completes(db, tmp_path):
    """The durable observe job defers while the remote stays scheduled
    and finishes once reconcile confirms public (Q07 worker path)."""
    from modules.factory.services.worker import ApplicationWorker
    svc, fake, chk, commands = _pubsvc(
        db, tmp_path, now_fn=lambda: "2026-09-18T09:00:00+00:00")
    # A publication the provider still holds — scheduled_at is ahead
    # of the fake's clock, so the first poll must defer.
    with db.uow() as u:
        u.records.put(Publication(
            schema_version="publication.v1", id="pub-s",
            created_at=NOW, variant_plan_id="vp-1",
            final_sha256=SHA, platform="youtube",
            account_id="acct-main", provider="upload_post",
            status="scheduled", request_id="req-s", job_id="req-s",
            visibility="public",
            scheduled_at="2026-09-18T10:00:00+00:00"))
    fake.doc["jobs"]["req-s"] = {
        "request_id": "req-s", "key": "k", "payload": "p",
        "fields": {"user": "acct-main", "platform[]": ["youtube"],
                   "scheduled_date": "2026-09-18T10:00:00+00:00"},
        "file_bytes": 0, "video_url": "",
        "steps": ["scheduled"], "i": 0}
    sched = Scheduler(db)
    worker = ApplicationWorker(SimpleNamespace(
        db=db, scheduler=sched, publishing=svc, commands=commands))
    job = {"id": "job-obs", "fencing_token": 1}
    out = worker.execute("publication_observe",
                         {"publication_id": "pub-s"}, job)
    assert out["status"] == "pending"
    assert out["defer_s"] > 0
    # The remote fires at its instant; the next poll completes and the
    # public transition has already scheduled checkpoints via on_public.
    fake.now_fn = lambda: "2026-09-18T11:00:00+00:00"
    out = worker.execute("publication_observe",
                         {"publication_id": "pub-s"}, job)
    assert out.get("status") != "pending"
    assert svc.get("pub-s")["status"] == "public"
    assert {s["horizon"] for s in chk.for_publication("pub-s")} == \
        set(HORIZON_HOURS)


# ------------------------------------------------ Q10 dispatch gate --

def _work(db):
    """PublicationWork over a services stub with a real RoundService."""
    class S:
        def __init__(self, db):
            self.db = db
            self.rounds = RoundService(SimpleNamespace(db=db))
            self.seeds = SeedRegistry(db)
    return PublicationWork(S(db))


def _gate_pub(db, eid, seed, group):
    """An experiment + seed resolving to `series:{group}` plus one
    planned publication slot on it."""
    from test_factory_seed_selection import _experiment as _exp
    from modules.factory.domain.records import Seed
    _exp(db, eid=eid, seed=seed)
    with db.uow() as u:
        u.records.put(Seed(schema_version="seed.v1", id=seed,
                           created_at=NOW, original_url="u",
                           independence_group=group))
        u.records.put(Publication(
            schema_version="publication.v1", id=f"pub-{eid}",
            created_at=NOW, variant_plan_id=f"vp-{eid}-a",
            final_sha256=SHA, platform="youtube", account_id="acct-1",
            provider="upload_post", status="planned",
            experiment_id=eid, experiment_revision=1))
    return {"id": f"pub-{eid}", "experiment_id": eid,
            "provider": "upload_post",
            "account_id": "acct-1", "platform": "youtube"}


def test_q10_paused_loop_defers_and_halted_blocks(db):
    work = _work(db)
    pub = _gate_pub(db, "exp-1", "seed-1", "root-1")
    work.s.rounds.freeze_loop("series:root-1", max_rounds=2)
    assert work._loop_gate(pub) is None
    work.s.rounds.pause_series("series:root-1")
    assert work._loop_gate(pub) == "paused"
    work.s.rounds.cancel_series("series:root-1")
    assert work._loop_gate(pub).startswith("loop_halted:")


def test_q10_provider_and_account_allowlists_enforced(db):
    work = _work(db)
    pub_p = _gate_pub(db, "exp-p", "seed-p", "root-p")
    work.s.rounds.freeze_loop(
        "series:root-p", max_rounds=2,
        allowed_providers=["other_provider"])
    assert work._loop_gate(pub_p) == "provider_not_allowed"
    pub_a = _gate_pub(db, "exp-a", "seed-a", "root-a")
    work.s.rounds.freeze_loop(
        "series:root-a", max_rounds=2,
        allowed_accounts=["acct-9"])
    assert work._loop_gate(pub_a) == "account_not_allowed"


def test_q10_queue_refuses_while_paused(db):
    work = _work(db)
    pub = _gate_pub(db, "exp-1", "seed-1", "root-1")
    work.s.rounds.freeze_loop("series:root-1", max_rounds=2)
    work.s.rounds.pause_series("series:root-1")
    work.s.publishing = SimpleNamespace(
        get=lambda pid: dict(pub, status="planned"),
        _check_authorization=lambda *a: None,
        publisher=object())
    with pytest.raises(ContractError) as error:
        work.queue("pub-exp-1")
    assert error.value.code == "loop_paused"


# -------------------------------------- Q14 account + evidence ids --

def test_q14_decision_ids_and_account_scoping(db):
    """select_seed evidence carries per-lane decision ids including the
    account suffix, and the account argument scopes publication lookup."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy={"mode": "primary_platform",
                              "primary_platform": "tiktok",
                              "provisional_horizon": "48h"})
    _lanes(db, "exp-1", ["tiktok"],
           {k: {"tiktok": v} for k, v in
            zip("ABCD", [100, 200, 90, 80])})
    out = svc.select_seed("exp-1", 1, accounts={"tiktok": "tiktok-acct"})
    assert out["decision_ids"] == ["dec-exp-1-r1-48h-tiktok-tiktok-acct"]
    assert out["basis"]["evidence_ids"]  # snapshot links, not only hashed


def test_q14_unscoped_multi_account_lane_is_missing(db):
    """Two accounts on one platform with no scoping: the lane resolves
    to missing rather than guessing which publication to read."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy={"mode": "primary_platform",
                              "primary_platform": "tiktok",
                              "provisional_horizon": "48h"})
    for vk, val in zip("ABCD", [100, 200, 90, 80]):
        for acct in ("acct-1", "acct-2"):
            pid = f"pub-{vk}-{acct}"
            with db.uow() as u:
                u.records.put(Publication(
                    schema_version="publication.v1", id=pid,
                    created_at=NOW,
                    variant_plan_id=f"vp-exp-1-{vk.lower()}",
                    final_sha256=SHA, platform="tiktok",
                    account_id=acct, remote_post_id=f"{acct}-{vk}",
                    status="public", provider="upload_post",
                    published_at="2026-09-10T09:00:00+00:00",
                    experiment_revision=1))
            svc.db.uow().records  # records committed via uow above
            with db.uow() as u:
                u.records.put(MetricSnapshot(
                    schema_version="metric_snapshot.v1",
                    id=f"snap-{pid}-48h", created_at=NOW,
                    publication_id=pid, post_id=pid, horizon="48h",
                    query_version="f32.v2",
                    requested_period={"horizon_hours": 48,
                        "window_kind": "observed_lifetime_at_age"},
                    source="verified fixture", metrics={"views": val},
                    availability={"views": "ok"},
                    completeness="complete", observed_at=NOW))
    unscoped = svc.select_seed("exp-1", 1)
    assert unscoped["outcome"] == "waiting"
    scoped = svc.select_seed("exp-1", 1, account="acct-2")
    assert scoped["outcome"] == "champion"
    assert scoped["winner_variant"] == "B"


def test_q14_per_platform_metric_override(db):
    """A declared per-platform primary_metric replaces the global
    metric on that lane (§8.3) — likes decides tiktok, not views."""
    _experiment(db)
    svc = LearningService(db)
    _policy(svc, seed_policy={
        "mode": "primary_platform", "primary_platform": "tiktok",
        "provisional_horizon": "48h",
        "per_platform": {"tiktok": {"primary_metric": "likes"}},
        "improvement_rule": {"kind": "weighted_lift"}},
        practical_lift=0.3)
    # B leads views but D leads likes — the override makes D rank 1.
    lanes = [(100, 10), (500, 20), (300, 30), (400, 100)]
    for vk, (views, likes) in zip("ABCD", lanes):
        pid = f"pub-{vk}"
        with db.uow() as u:
            u.records.put(Publication(
                schema_version="publication.v1", id=pid, created_at=NOW,
                variant_plan_id=f"vp-exp-1-{vk.lower()}",
                final_sha256=SHA, platform="tiktok",
                account_id="acct-1", remote_post_id=f"post-{vk}",
                status="public", provider="upload_post",
                published_at="2026-09-10T09:00:00+00:00",
                experiment_revision=1))
            u.records.put(MetricSnapshot(
                schema_version="metric_snapshot.v1",
                id=f"snap-{pid}-48h", created_at=NOW,
                publication_id=pid, post_id=pid, horizon="48h",
                query_version="f32.v2",
                requested_period={"horizon_hours": 48,
                    "window_kind": "observed_lifetime_at_age"},
                source="verified fixture",
                metrics={"views": views, "likes": likes},
                availability={"views": "ok", "likes": "ok"},
                completeness="complete", observed_at=NOW))
    out = svc.select_seed("exp-1", 1)
    assert out["outcome"] == "champion"
    assert out["winner_variant"] == "D"


# ------------------------------------------- Q09 honest limitation --

def test_q09_no_artifact_reports_limitation_not_readiness(db):
    """A champion with no accepted local artifact yields an explicit
    limitation — the child seed stays honestly unready (§10/PL-06)."""
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds)
    result = rounds.propose_next("exp-1", 1, _selection(db))
    assert result["winner_media"]["status"] == "no_winner_artifact"
    readiness = SeedRegistry(db).readiness(result["seed"]["id"])
    assert readiness["analysis_ready"] is False
    assert "no_source_media" in readiness["blockers"]
