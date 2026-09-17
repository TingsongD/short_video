from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
"""F31 publishing: manual lane, authorised automated lane, async
states, idempotency, cadence/timezone, ambiguous publish, OAuth
expiry, actual post verification."""
import json
import hashlib
from datetime import datetime,timedelta,timezone

import pytest

from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import Authorization
from modules.factory.integrations.publisher import (
    PublishTransportError, UploadPostPublisher)
from modules.factory.publishing.service import PublishingService
from modules.factory.store import Database
from modules.factory.testing.fakes import FakePublisher

NOW = "2026-09-17T12:00:00+00:00"
SHA = hashlib.sha256(b'v').hexdigest()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "f.db")


def _auth(db, aid="auth-1", pub=True, status="authorized", until=""):
    a = Authorization(schema_version="authorization.v1", id=aid,
                      created_at=NOW, scope_hash="sc",
                      publication_authorized=pub, status=status,
                      valid_until=until)
    with db.uow() as u:
        u.records.put(a)
    return aid


def _svc(db, pub=None, users=None, max_per_day=2):
    accounts = {"youtube:acct-main": "acct-main"}
    for u in (users or []):
        accounts[f"youtube:{u}"] = u
    remote = pub or FakePublisher()
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=remote.transport,verifier=remote.verify_post)
    svc=PublishingService(db, publisher=adapter, effects=FixtureEffects(db, Executor(db)),
                             accounts=accounts,
                             max_per_day=max_per_day)
    svc.fixture_remote=remote
    return svc


def _plan(svc, pid="pub-1", **kw):
    args = dict(variant_plan_id="vp-1", final_sha256=SHA,
                platform="youtube", account_id="acct-main",
                metadata={"title": "T", "description": "d",
                          "hashtags": ["a"]},
                authorization_id="auth-1")
    args.update(kw)
    p=svc.plan(pid, **args)
    row=svc.db.uow().records.get('authorization',args['authorization_id']) if args.get('authorization_id') else None
    raw=json.loads(row['body']) if row else {}
    if raw.get('status')=='authorized' and raw.get('publication_authorized') and (not raw.get('valid_until') or raw['valid_until']>NOW):
        from modules.factory.execution.effects import EffectService
        intent=json.loads(svc.db.uow().records.get('publicationintent','intent:'+pid)['body'])
        auth=Authorization(schema_version='authorization.v1',id='approve:'+pid,created_at=NOW,scope_hash=intent['plan_hash'],status='authorized',publication_authorized=True,
            allowed_providers=['upload_post'],allowed_models={'upload_post':['upload']},valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),authorizing_action='fixture operator')
        EffectService(svc.db).approve(auth,'publicationintent',intent['id'],[dict(key='publish',kind='publication',provider='upload_post',model='upload',account=p.account_id,request=intent['request'])],[])
        svc.authorize(pid,auth.id)
    return p


# ------------------------------------------------------------- plan --

def test_plan_persists_intent_before_transport(db):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    p = svc.get("pub-1")
    assert p["status"] == "requested"
    assert p["idempotency_key"]
    assert pub.sent == []                      # no transport call yet


def test_plan_rejects_unknown_account_and_platform(db):
    svc = _svc(db)
    _auth(db)
    with pytest.raises(ContractError) as e:
        _plan(svc, account_id="ghost")
    assert e.value.code == "unknown_account"
    with pytest.raises(ContractError) as e2:
        _plan(svc, pid="pub-2", platform="tiktok")
    assert e2.value.code == "unqualified_platform"


def test_publish_requires_authorization(db):
    svc = _svc(db)
    _plan(svc, authorization_id="")
    with pytest.raises(ContractError) as e:
        svc.publish("pub-1", video_path="/v.mp4", now=NOW)
    assert e.value.code == "publication_not_authorized"


def test_publish_rejects_revoked_or_expired_auth(db):
    svc = _svc(db)
    _auth(db, aid="auth-1", status="revoked")
    _plan(svc)
    with pytest.raises(ContractError):
        svc.publish("pub-1", video_path="/v.mp4", now=NOW)


def test_expired_authorization_blocks(db):
    svc = _svc(db)
    _auth(db, until="2026-09-01T00:00:00+00:00")
    _plan(svc)
    with pytest.raises(ContractError) as e:
        svc.publish("pub-1", video_path="/v.mp4", now=NOW)
    assert e.value.code == "authorization_expired"


# -------------------------------------------------------- transport --

def test_upload_sends_bytes_fields_and_idempotency(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc,final_sha256=hashlib.sha256(b"\x00\x01realvideobytes").hexdigest())
    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00\x01realvideobytes")
    svc.publish("pub-1", video_path=str(video), now=NOW)
    req = pub.sent[0]
    assert req["file"]["bytes"] == b"\x00\x01realvideobytes"
    assert req["file"]["name"] == "video"
    assert req["fields"]["user"] == "acct-main"
    assert req["fields"]["platform[]"] == ["youtube"]
    assert req["headers"]["Idempotency-Key"] == \
        svc.get("pub-1")["idempotency_key"]
    assert str(tmp_path) not in json.dumps(req["fields"])


def test_service_requires_verified_final_bytes_for_remote_url(db):
    pub=FakePublisher();svc=_svc(db,pub);_auth(db)
    _plan(svc,media_url='https://cdn.example.com/f.mp4')
    with pytest.raises(ContractError,match='final_bytes_required'):svc.publish('pub-1',now=NOW)
    assert not pub.sent


def test_adapter_requires_user_platforms_and_key():
    c = UploadPostPublisher(api_key="k", transport=lambda r: {})
    with pytest.raises(ValueError):
        c.upload(video_url="https://x/v.mp4", platforms=("youtube",),
                 idempotency_key="k1")            # no user
    with pytest.raises(ValueError):
        c.upload(video_url="https://x/v.mp4", user="u",
                 idempotency_key="k1")            # no platforms
    with pytest.raises(ValueError):
        c.upload(video_url="https://x/v.mp4", user="u",
                 platforms=("youtube",))          # no idem key
    with pytest.raises(ValueError):
        c.upload(user="u", platforms=("youtube",),
                 idempotency_key="k1")            # no media at all


# ------------------------------------------------------ async state --

def test_accepted_processing_then_public(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    out = svc.publish("pub-1", video_path=str(v), now=NOW)
    assert out["status"] == "uploading"        # accepted ≠ public
    assert svc.get("pub-1")["published_at"] == ""
    r1 = svc.reconcile("pub-1")
    assert r1["status"] == "processing"
    r2 = svc.reconcile("pub-1")
    assert r2["status"] == "public"
    p = svc.get("pub-1")
    assert p["published_at"] == NOW            # provider-confirmed
    assert p["remote_post_id"].startswith("yt-")
    assert p["post_url"].startswith("https://youtu.be/")


def test_sync_request_becoming_async(db, tmp_path):
    pub = FakePublisher(faults={"sync_terminal"})
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    out = svc.publish("pub-1", video_path=str(v), now=NOW)
    assert out["status"] == "processing"       # sync resp mid-flight
    assert svc.reconcile("pub-1")["status"] == "public"


def test_draft_is_not_public(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc, visibility="draft")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    svc.reconcile("pub-1")
    p = svc.get("pub-1")
    assert p["status"] == "draft"
    assert p["published_at"] == ""
    assert p["remote_post_id"] == ""           # draft ≠ a post


def test_scheduled_is_not_public(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc, scheduled_at="2026-09-20T15:00:00+00:00")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    svc.reconcile("pub-1")
    p = svc.get("pub-1")
    assert p["status"] == "scheduled"
    assert p["published_at"] == ""


# ------------------------------------------------------ idempotency --

def test_same_key_same_payload_dedups(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    # simulate a blind resubmit with the same key+payload
    c = UploadPostPublisher(api_key="k", user="acct-main",
                            transport=pub.transport)
    again = c.upload(video_path=str(v), title="T", description="d",
                     platforms=("youtube",), visibility="public",
                     user="acct-main",
                     idempotency_key=svc.get("pub-1")["idempotency_key"],
                     extra_fields={"hashtags": "a","timezone":"UTC"})
    assert again["request_id"] == svc.get("pub-1")["request_id"]
    svc.reconcile("pub-1")
    svc.reconcile("pub-1")
    assert pub.public_post_count() == 1        # no duplicate post


def test_same_key_different_payload_conflicts():
    pub = FakePublisher()
    c = UploadPostPublisher(api_key="k", user="acct-main",
                            transport=pub.transport)
    c.upload(video_url="https://x/a.mp4", user="acct-main",
             platforms=("youtube",), idempotency_key="k-1")
    with pytest.raises(PublishTransportError) as e:
        c.upload(video_url="https://x/b.mp4", user="acct-main",
                 platforms=("youtube",), idempotency_key="k-1")
    assert e.value.status_code == 409


# ---------------------------------------------------- lost ack etc --

def test_lost_ack_reconciles_without_duplicate(db, tmp_path):
    pub = FakePublisher(faults={"lost_ack"})
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    out = svc.publish("pub-1", video_path=str(v), now=NOW)
    assert out["status"] in ("uploading", "processing", "public")
    # restart: new service, same remote world, reconcile by key
    svc2 = _svc(db, pub)
    for _ in range(3):
        out2 = svc2.reconcile("pub-1")
    assert out2["status"] == "public"
    assert pub.public_post_count() == 1


def test_no_remote_effect_is_safe_to_resubmit(db):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    out = svc.reconcile("pub-1")               # never submitted
    assert out == {"status": "requested",
                   "action": "safe_to_resubmit"}


def test_expired_oauth_marks_failed_not_public(db, tmp_path):
    pub = FakePublisher(faults={"oauth_expired"})
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    with pytest.raises(PublishTransportError):
        svc.publish("pub-1", video_path=str(v), now=NOW)
    assert svc.get("pub-1")["status"] == "failed"
    assert "401" in svc.get("pub-1")["last_error"]


def test_unreachable_status_keeps_unknown(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)
    pub.faults.add("lost_status")
    out = svc.reconcile("pub-1")
    assert out["status"] == "unknown"
    assert svc.get("pub-1")["status"] == "unknown"


# --------------------------------------------------------- cadence --

def _public_post(svc, pid, day):
    svc.fixture_remote.plant_post(f'yt-{pid}',published_at=day)
    svc.register_manual(
        pid, variant_plan_id="vp-x", final_sha256="cd" * 32,
        platform="youtube", account_id="acct-main",
        remote_post_id=f"yt-{pid}", published_at=day, verify=True)


def test_cadence_blocks_before_submission(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub, max_per_day=2)
    _auth(db)
    _public_post(svc, "m-1", "2026-09-17T08:00:00+00:00")
    _public_post(svc, "m-2", "2026-09-17T09:00:00+00:00")
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    with pytest.raises(ContractError) as e:
        svc.publish("pub-1", video_path=str(v), now=NOW)
    assert e.value.code == "cadence_blocked"
    assert pub.sent == []                      # blocked pre-transport


def test_cadence_uses_configured_timezone_dst(db):
    """23:30 UTC on Sep 17 is still Sep 17 in New York (EDT, UTC-4)
    but Sep 17 boundary differs across the DST divide."""
    svc = _svc(db, max_per_day=1)
    _auth(db)
    # a post at 2026-03-08T07:30Z = 02:30 EST (the skipped DST hour
    # region); cadence day in America/New_York is Mar 8.
    _public_post(svc, "m-1", "2026-03-08T07:30:00+00:00")
    _plan(svc, tz="America/New_York")
    v_err = None
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".mp4",
                                     delete=False) as f:
        f.write(b"v")
        path = f.name
    try:
        svc.publish("pub-1", video_path=path,
                    now="2026-03-08T20:00:00+00:00")  # 16:00 EDT Mar 8
    except ContractError as e:
        v_err = e
    os.unlink(path)
    assert v_err and v_err.code == "cadence_blocked"


def test_different_account_has_separate_cadence(db, tmp_path):
    pub = FakePublisher(users=("acct-main", "acct-2"))
    svc = _svc(db, pub, users=("acct-2",), max_per_day=1)
    _auth(db)
    _public_post(svc, "m-1", "2026-09-17T08:00:00+00:00")
    _plan(svc, account_id="acct-2")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    svc.publish("pub-1", video_path=str(v), now=NOW)   # not blocked
    assert len(pub.sent) == 1


# ----------------------------------------------------------- manual --

def test_manual_registration_verifies_real_post(db):
    pub = FakePublisher()
    pub.plant_post("yt-man1", account="acct-main")
    svc = _svc(db, pub)
    p = svc.register_manual(
        "pub-m1", variant_plan_id="vp-1", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id="yt-man1",
        published_at="2026-09-10T09:00:00+00:00")
    assert p.status == "public"
    assert p.manual is True
    assert p.post_url == "https://youtu.be/yt-man1"


def test_manual_rejects_unverified_or_wrong_account(db):
    pub = FakePublisher()
    svc = _svc(db, pub)
    with pytest.raises(ContractError) as e:
        svc.register_manual(
            "pub-m1", variant_plan_id="vp-1", final_sha256=SHA,
            platform="youtube", account_id="acct-main",
            remote_post_id="yt-ghost",
            published_at="2026-09-10T09:00:00+00:00")
    assert e.value.code == "post_not_found"
    pub.plant_post("yt-other", account="someone-else")
    with pytest.raises(ContractError) as e2:
        svc.register_manual(
            "pub-m2", variant_plan_id="vp-1", final_sha256=SHA,
            platform="youtube", account_id="acct-main",
            remote_post_id="yt-other",
            published_at="2026-09-10T09:00:00+00:00")
    assert e2.value.code == "post_wrong_account"


def test_one_post_cannot_map_two_variants(db):
    pub = FakePublisher()
    pub.plant_post("yt-man1")
    svc = _svc(db, pub)
    svc.register_manual(
        "pub-m1", variant_plan_id="vp-a", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id="yt-man1",
        published_at="2026-09-10T09:00:00+00:00")
    with pytest.raises(ContractError) as e:
        svc.register_manual(
            "pub-m2", variant_plan_id="vp-b", final_sha256="ef" * 32,
            platform="youtube", account_id="acct-main",
            remote_post_id="yt-man1",
            published_at="2026-09-10T09:00:00+00:00")
    assert e.value.code == "post_mapping_conflict"


def test_metadata_and_delete_are_explicit(db):
    pub = FakePublisher()
    pub.plant_post("yt-man1")
    svc = _svc(db, pub)
    svc.register_manual(
        "pub-m1", variant_plan_id="vp-1", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id="yt-man1",
        published_at="2026-09-10T09:00:00+00:00")
    svc.update_metadata("pub-m1", {"title": "new title"})
    assert pub.doc["posts"]["yt-man1"]["title"] == "new title"
    svc.delete_post("pub-m1", now=NOW)
    p = svc.get("pub-m1")
    assert p["status"] == "public"             # history preserved
    assert p["deleted_at"] == NOW
    assert pub.doc["posts"]["yt-man1"]["status"] == "deleted"


def test_retry_resubmits_only_when_no_effect(db, tmp_path):
    pub = FakePublisher()
    svc = _svc(db, pub)
    _auth(db)
    _plan(svc)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"v")
    out = svc.retry("pub-1", video_path=str(v), now=NOW)
    assert out["status"] in ("uploading", "processing")
    out2 = svc.retry("pub-1", video_path=str(v), now=NOW)
    assert out2["status"] != "requested"       # no second submit
    assert len([r for r in pub.sent if r["method"] == "POST"]) == 1


def test_horizon_policy_stored_with_intent(db):
    svc = _svc(db)
    _auth(db)
    _plan(svc, horizon_policy={"horizon": "7d",
                               "primary_metric": "views",
                               "min_exposure": 100})
    assert svc.get("pub-1")["horizon_policy"]["horizon"] == "7d"
