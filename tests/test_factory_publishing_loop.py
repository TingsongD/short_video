"""PL-03/PL-10: multi-destination publication slots, provider binding
and remote scheduled-job cancellation outcomes."""
import json
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import Authorization
from modules.factory.integrations.publisher import (
    PublishTransportError, UploadPostPublisher)
from modules.factory.publishing.service import PublishingService
from modules.factory.store import Database
from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
from modules.factory.testing.fakes import FakePublisher
from test_factory_application import (
    application, prepare, quote_and_run)

NOW = "2026-09-17T12:00:00+00:00"
SHA = hashlib.sha256(b'v').hexdigest()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _auth(db, aid="auth-1"):
    a = Authorization(schema_version="authorization.v1", id=aid,
                      created_at=NOW, scope_hash="sc",
                      publication_authorized=True, status="authorized")
    with db.uow() as u:
        u.records.put(a)


def _svc(db, pub=None, accounts=None):
    remote = pub or FakePublisher()
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=remote.transport,
                                  verifier=remote.verify_post)
    svc = PublishingService(
        db, publisher=adapter, effects=FixtureEffects(db, Executor(db)),
        accounts=accounts or {"youtube:acct-main": "acct-main"},
        max_per_day=20)
    svc.fixture_remote = remote
    return svc


def _plan(svc, pid="pub-1", **kw):
    args = dict(variant_plan_id="vp-1", final_sha256=SHA,
                platform="youtube", account_id="acct-main",
                metadata={"title": "T", "description": "d"},
                authorization_id="auth-1")
    args.update(kw)
    p = svc.plan(pid, **args)
    row = svc.db.uow().records.get('publicationintent', 'intent:' + pid)
    intent = json.loads(row['body'])
    auth = Authorization(
        schema_version='authorization.v1', id='approve:' + pid,
        created_at=NOW, scope_hash=intent['plan_hash'],
        status='authorized', publication_authorized=True,
        allowed_providers=['upload_post'],
        allowed_models={'upload_post': ['upload']},
        valid_until=(datetime.now(timezone.utc) +
                     timedelta(hours=1)).isoformat(),
        authorizing_action='fixture operator')
    from modules.factory.execution.effects import EffectService
    EffectService(svc.db).approve(
        auth, 'publicationintent', intent['id'],
        [dict(key='publish', kind='publication', provider='upload_post',
              model='upload', account=p.account_id,
              request=intent['request'])], [])
    svc.authorize(pid, auth.id)
    return p


# ------------------------------------------------------ provider --

def test_plan_stamps_provider_and_slot(db):
    svc = _svc(db)
    _auth(db)
    _plan(svc, provider="upload_post", connection_id="conn-1")
    p = svc.get("pub-1")
    assert p["provider"] == "upload_post"
    assert p["connection_id"] == "conn-1"


def test_manual_lane_accepts_other_platforms(db):
    svc = _svc(db, accounts={"tiktok:tt-1": "tt-1"})
    svc.fixture_remote.plant_post(
        "tt-9", platform="tiktok", account="tt-1",
        url="https://tiktok.com/@x/video/tt-9")
    p = svc.register_manual(
        "pub-man", variant_plan_id="vp-1", final_sha256=SHA,
        platform="tiktok", account_id="tt-1",
        remote_post_id="tt-9",
        published_at="2026-09-16T10:00:00+00:00", now=NOW)
    assert p.platform == "tiktok"
    assert p.status == "public"


# ------------------------------------------------------ cancel ----

def _scheduled(db, tmp_path, svc):
    _auth(db)
    _plan(svc, scheduled_at="2026-09-20T15:00:00+00:00")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    svc.reconcile("pub-1")
    p = svc.get("pub-1")
    assert p["status"] == "scheduled" and p["job_id"], p
    return p


def test_cancel_remote_scheduled_job(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _scheduled(db, tmp_path, svc)
    out = svc.cancel_remote("pub-1")
    assert out["outcome"] == "cancelled", out
    assert svc.get("pub-1")["status"] == "cancelled"


def test_cancel_remote_public_race_is_already_public(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _scheduled(db, tmp_path, svc)
    job = svc.get("pub-1")["job_id"]
    doc = pub.doc["jobs"][job]
    doc["steps"] = ["accepted", "scheduled", "public"]
    doc["i"] = 2                     # raced to live before the cancel
    out = svc.cancel_remote("pub-1")
    assert out["outcome"] == "already_public", out
    # A post that raced to live is never reported cancelled.
    assert svc.get("pub-1")["status"] == "public"


def test_cancel_remote_failure_keeps_schedule(db, tmp_path):
    pub = FakePublisher()
    pub.faults.add("cancel_fails")
    svc = _svc(db, pub)
    _scheduled(db, tmp_path, svc)
    out = svc.cancel_remote("pub-1")
    assert out["outcome"] == "cancel_failed", out
    assert svc.get("pub-1")["status"] == "scheduled"


def test_cancel_remote_local_states_not_scheduled(db):
    svc = _svc(db)
    _auth(db)
    _plan(svc)
    out = svc.cancel_remote("pub-1")
    assert out["outcome"] == "not_scheduled"
    assert svc.get("pub-1")["status"] == "requested"


# --------------------------------------------------------- batch --

def _publishable(application, policy_extra=None):
    """prepare → run → reviews → verified delivery for all 4 variants;
    freeze the decision policy; return variant ids."""
    s, c, act, w, root = application
    body, art = prepare(application)
    plan = quote_and_run(application)
    r = act('post', '/api/experiments/fixture-exp/assets/review',
            {'plan_hash': plan['plan_hash'],
             'reviewer': 'fixture-operator', 'artifact_ids': [art],
             'verdict': 'pass'}, rev=1)
    assert r.status_code == 200, r.text
    for _ in range(30):
        if w.tick() is None:
            break
    variants = s.experiment_results('fixture-exp')['variants']
    for variant in variants:
        final = variant['final']
        vid = variant['id']
        r = act('post', f'/api/variants/{vid}/reviews',
                {'check_type': 'creative', 'verdict': 'pass',
                 'target_hash': final['sha256'],
                 'reviewer': 'fixture-operator'})
        assert r.status_code == 201, r.text
        r = act('post', f'/api/variants/{vid}/deliver',
                {'folder_id': 'folder', 'reviewer': 'fixture-operator',
                 'account': 'fixture-drive',
                 'valid_until': (datetime.now(timezone.utc) +
                                 timedelta(hours=1)).isoformat(),
                 'artifact_id': final['artifact_id'],
                 'target_hash': final['sha256'],
                 'check_ids': final['check_ids'] +
                 [r.json()['review']['id']]}, rev=1)
        assert r.status_code == 202, r.text
        out = w.tick()
        assert out['status'] == 'verified', out
    policy_body = {'policy_version': 'v1',
                   'primary_metric': 'avg_view_pct',
                   'horizon': '24h', 'min_exposure': 10,
                   'practical_lift': 0.05, 'exposure_metric': 'views',
                   'reviewer': 'fixture-operator'}
    policy_body.update(policy_extra or {})
    r = act('post', '/api/experiments/fixture-exp/policy',
            policy_body, rev=1)
    assert r.status_code in (200, 201), r.text
    return [v['id'] for v in variants]


def _multi_account_app(tmp_path):
    from modules.factory.bootstrap import bootstrap
    from modules.factory.api.app import create_app
    from modules.factory.services.worker import ApplicationWorker
    from fastapi.testclient import TestClient
    from test_factory_application import DiskDrive
    remote = FakePublisher()
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=remote.transport,
                                  verifier=remote.verify_post)
    accounts = {"youtube:acct-main": "acct-main",
                "tiktok:tt-1": "tt-1",
                "instagram:ig-1": "ig-1",
                "facebook:fb-1": "fb-1"}
    service = bootstrap(tmp_path, drive=DiskDrive(tmp_path / 'remote'),
                        publisher=adapter,
                        settings={'drive_folder_id': 'folder',
                                  'raise_worker_errors': True,
                                  'publication_accounts': accounts,
                                  'posts_per_day': 40})
    service.fixture_remote = remote
    client = TestClient(create_app(service, session_token='test-session'))
    seq = [0]
    def action(method, path, body=None, rev=None, **kwargs):
        seq[0] += 1
        headers = {'x-csrf-token': 'test-session',
                   'idempotency-key': kwargs.pop('key', f'action-{seq[0]}')}
        if rev is not None:
            headers['x-expected-revision'] = str(rev)
        headers.update(kwargs.pop('headers', {}))
        return getattr(client, method)(path, json=body,
                                       headers=headers, **kwargs)
    return service, client, action, ApplicationWorker(service), tmp_path


@pytest.fixture
def app4(tmp_path):
    svc = _multi_account_app(tmp_path)
    yield svc
    svc[0].db.close()


def test_batch_plans_sixteen_destination_slots(app4):
    s, c, act, w, root = app4
    vids = _publishable(app4)
    dests = [{'platform': p, 'account_id': a}
             for p, a in [('youtube', 'acct-main'), ('tiktok', 'tt-1'),
                          ('instagram', 'ig-1'), ('facebook', 'fb-1')]]
    r = act('post', '/api/experiments/fixture-exp/publications',
            {'destinations': dests, 'reviewer': 'fixture-operator',
             'check_ids': []}, rev=1)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out['slots'] == 16
    assert len(out['publications']) == 16, out['errors']
    assert out['errors'] == []
    slots = {(p['variant_plan_id'], p['platform'])
             for p in out['publications']}
    assert len(slots) == 16
    assert all(p['provider'] == 'upload_post'
               for p in out['publications'])
    assert all(p['status'] == 'requested'
               for p in out['publications'])


def test_batch_partial_failure_lists_slot_errors(app4):
    s, c, act, w, root = app4
    _publishable(app4)
    dests = [{'platform': 'youtube', 'account_id': 'acct-main'},
             {'platform': 'tiktok', 'account_id': 'ghost'}]
    r = act('post', '/api/experiments/fixture-exp/publications',
            {'destinations': dests, 'reviewer': 'fixture-operator',
             'check_ids': []}, rev=1)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out['slots'] == 8
    assert len(out['publications']) == 4
    assert len(out['errors']) == 4
    assert {e['code'] for e in out['errors']} == {'unknown_account'}


def test_batch_requires_destinations(app4):
    s, c, act, w, root = app4
    _publishable(app4)
    r = act('post', '/api/experiments/fixture-exp/publications',
            {'reviewer': 'fixture-operator'}, rev=1)
    assert r.status_code == 400
    assert r.json()['error'] == 'destinations_required'


def test_publish_authorize_scope_mismatch_rejected(db):
    svc = _svc(db)
    _auth(db)
    _plan(svc)
    from modules.factory.services.publication_work import (
        PublicationWork)
    from types import SimpleNamespace
    work = PublicationWork(SimpleNamespace(
        publishing=svc, db=db, detail=lambda k, i: None,
        commands=None, executor=None))
    with pytest.raises(ContractError) as e:
        work.authorize('pub-1', {'final_sha256': 'other',
                                 'platform': 'youtube',
                                 'account_id': 'acct-main',
                                 'action': 'publish',
                                 'reviewer': 'op'})
    assert e.value.code == 'publication_scope_mismatch'
