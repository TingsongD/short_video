from modules.factory.testing.authority import FixtureEffects
from modules.factory.execution import Executor
"""F31 manual scenarios: manual mapping conflicts, wire-contract
inspection, lost-ack reconcile + cadence, live-gate shape."""
import json

from .cases_f01 import CaseContext, _result
from ..domain.errors import ContractError
from ..domain.records import Authorization
from ..integrations.publisher import UploadPostPublisher
from ..publishing.service import PublishingService
from ..store import Database
from ..testing.fakes import FakePublisher

NOW = "2026-09-17T12:00:00+00:00"
SHA = "ab" * 32


def _db(ctx, name):
    return Database(ctx.run_dir / f"{name}.db")


def _svc(db, remote, max_per_day=2):
    adapter = UploadPostPublisher(api_key="k", user="acct-main",
                                  transport=remote.transport)
    return PublishingService(
        db, publisher=adapter,
        accounts={"youtube:acct-main": "acct-main"},
        max_per_day=max_per_day)


def _auth(db):
    with db.uow() as u:
        u.records.put(Authorization(
            schema_version="authorization.v1", id="auth-1",
            created_at=NOW, scope_hash="sc",
            publication_authorized=True, status="authorized"))


def _video(ctx):
    p = ctx.run_dir / "final.mp4"
    p.write_bytes(b"\x00\x01factory-final")
    return str(p)


def f31_m01(ctx: CaseContext):
    """Register manual post links; assigning one post to two variants
    must conflict, not double-count."""
    remote = FakePublisher()
    db = _db(ctx, "m01")
    svc = _svc(db, remote)
    for i in range(1, 4):
        remote.plant_post(f"yt-m{i}")
    for i in range(1, 4):
        svc.register_manual(
            f"pub-m{i}", variant_plan_id=f"vp-{i}", final_sha256=SHA,
            platform="youtube", account_id="acct-main",
            remote_post_id=f"yt-m{i}",
            published_at="2026-09-10T09:00:00+00:00")
    conflict = None
    try:
        svc.register_manual(
            "pub-m4", variant_plan_id="vp-4", final_sha256="cd" * 32,
            platform="youtube", account_id="acct-main",
            remote_post_id="yt-m1",
            published_at="2026-09-10T10:00:00+00:00")
    except ContractError as e:
        conflict = e.code
    checks = {
        "three_mappings": len(svc.list()) == 3,
        "conflict_rejected": conflict == "post_mapping_conflict",
        "not_double_counted": len(svc.list()) == 3,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f31_m02(ctx: CaseContext):
    """Inspect the fake transport's actual wire request: bytes (not a
    local path), required fields, idempotency identity; accepted ->
    processing -> public; separately draft-only."""
    remote = FakePublisher()
    db = _db(ctx, "m02")
    svc = _svc(db, remote)
    _auth(db)
    svc.plan("pub-1", variant_plan_id="vp-1", final_sha256=SHA,
             platform="youtube", account_id="acct-main",
             metadata={"title": "T", "description": "d",
                       "hashtags": ["x"]}, authorization_id="auth-1")
    svc.publish("pub-1", video_path=_video(ctx), now=NOW)
    req = remote.sent[0]
    svc.reconcile("pub-1")
    out = svc.reconcile("pub-1")
    # draft lane
    svc.plan("pub-d", variant_plan_id="vp-1", final_sha256="cd" * 32,
             platform="youtube", account_id="acct-main",
             visibility="draft", authorization_id="auth-1")
    svc.publish("pub-d", video_path=_video(ctx), now=NOW)
    svc.reconcile("pub-d")
    d = svc.get("pub-d")
    checks = {
        "bytes_not_path": req["file"]["bytes"] ==
        b"\x00\x01factory-final",
        "user_field": req["fields"]["user"] == "acct-main",
        "platform_field": req["fields"]["platform[]"] == ["youtube"],
        "idem_header": bool(req["headers"].get("Idempotency-Key")),
        "no_local_path_field": str(ctx.run_dir) not in
        json.dumps(req["fields"]),
        "progression_public": out["status"] == "public"
        and svc.get("pub-1")["published_at"],
        "draft_unpublished": d["status"] == "draft"
        and not d["published_at"],
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f31_m03(ctx: CaseContext):
    """Lose the publish ack, restart, reconcile — no duplicate post.
    A cadence conflict blocks before submission."""
    remote = FakePublisher(faults={"lost_ack"})
    db = _db(ctx, "m03")
    svc = _svc(db, remote)
    _auth(db)
    svc.plan("pub-1", variant_plan_id="vp-1", final_sha256=SHA,
             platform="youtube", account_id="acct-main",
             authorization_id="auth-1")
    svc.publish("pub-1", video_path=_video(ctx), now=NOW)
    svc2 = _svc(db, remote)                  # restart, same world
    last = {}
    for _ in range(4):
        last = svc2.reconcile("pub-1")
    # cadence: two public posts today on this account, cap 2
    remote.plant_post("yt-c1")
    remote.plant_post("yt-c2")
    svc2.register_manual(
        "pub-c1", variant_plan_id="vp-9", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id="yt-c1",
        published_at="2026-09-17T08:00:00+00:00")
    svc2.register_manual(
        "pub-c2", variant_plan_id="vp-8", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id="yt-c2",
        published_at="2026-09-17T09:00:00+00:00")
    svc2.plan("pub-2", variant_plan_id="vp-2", final_sha256="ef" * 32,
              platform="youtube", account_id="acct-main",
              authorization_id="auth-1")
    sent_before = len(remote.sent)
    blocked = None
    try:
        svc2.publish("pub-2", video_path=_video(ctx), now=NOW)
    except ContractError as e:
        blocked = e.code
    checks = {
        "reconciled_public": last["status"] == "public",
        "no_duplicate_post": remote.public_post_count() == 3,
        "cadence_blocked": blocked == "cadence_blocked",
        "blocked_pre_transport": len(remote.sent) == sent_before,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f31_m04(ctx: CaseContext):
    """Live gate: with no authorised live publisher the case stays
    pending while the engineering evidence (manual registration shape)
    is exercised."""
    remote = FakePublisher()
    db = _db(ctx, "m04")
    svc = _svc(db, remote)
    remote.plant_post("yt-live1", account="acct-main")
    p = svc.register_manual(
        "pub-live", variant_plan_id="vp-1", final_sha256=SHA,
        platform="youtube", account_id="acct-main",
        remote_post_id="yt-live1",
        published_at="2026-09-16T18:00:00+00:00")
    checks = {
        "verified_mapping": p.remote_post_id == "yt-live1"
        and p.status == "public",
        "account_checked": p.account_id == "acct-main",
    }
    return _result(
        ctx, "awaiting_manual_review",
        "engineering evidence recorded; live posting scope is a "
        "separate authorisation — verify one real manually posted "
        "final on the actual account before enabling",
        detail=checks)


def implementations():
    return {"F31-M01": f31_m01, "F31-M02": f31_m02,
            "F31-M03": f31_m03, "F31-M04": f31_m04}
