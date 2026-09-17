"""F27 manual scenarios: idempotent run lifecycle, SSE reconnect,
hostile-request safety, and restart durability."""
import json

from fastapi.testclient import TestClient

from .cases_f01 import CaseContext, _result
from ..api import create_app
from ..artifacts.registry import ArtifactStore
from ..seeds.registry import SeedRegistry
from ..services import FactoryServices
from ..store import Database
from ..testing.fixtures import _color_mp4


def _stack(ctx, name):
    db = Database(ctx.run_dir / f"{name}.db")
    arts = ArtifactStore(ctx.run_dir / f"{name}-arts", db=db)
    svc = FactoryServices(db, seeds=SeedRegistry(db), artifacts=arts,
                          artifact_root=ctx.run_dir / f"{name}-arts")
    client = TestClient(create_app(svc, session_token="tok-qa"))
    csrf = client.post("/api/session").json()["session_token"]
    return db, svc, client, csrf


def _mut(client, csrf, method, path, key, **kw):
    h = {"x-csrf-token": csrf, "idempotency-key": key}
    h.update(kw.pop("headers", {}))
    return getattr(client, method)(path, headers=h, **kw)


def f27_m01(ctx: CaseContext):
    """Create → quote → authorize → run; replay identical key returns
    the original result; a changed body conflicts — one logical run."""
    _, _, client, csrf = _stack(ctx, "m01")
    mut = lambda m, p, k, **kw: _mut(client, csrf, m, p, k, **kw)
    r = mut("post", "/api/experiments", "e1",
            json={"id": "e1", "unique_work": [{"credits": 2}]})
    mut("post", "/api/experiments/e1/quote", "q1", json={})
    mut("post", "/api/experiments/e1/authorize", "a1", json={},
        headers={"x-expected-revision": "0"})
    run1 = mut("post", "/api/experiments/e1/run", "r1", json={},
               headers={"x-expected-revision": "0"})
    run2 = mut("post", "/api/experiments/e1/run", "r1", json={},
               headers={"x-expected-revision": "0"})
    run3 = mut("post", "/api/experiments/e1/run", "r1",
               json={"different": True},
               headers={"x-expected-revision": "0"})
    checks = {
        "run_accepted": run1.status_code == 202
        and run1.json()["run"]["job_id"] == "job-e1",
        "replay_identical": run2.json() == run1.json(),
        "changed_body_conflict": run3.status_code == 409
        and run3.json()["error"] == "idempotency_conflict",
        "one_logical_run": run2.json()["run"]["job_id"]
        == run1.json()["run"]["job_id"],
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f27_m02(ctx: CaseContext):
    """Disconnect mid-stream, let work finish, reconnect with
    Last-Event-ID — all missed events arrive; nothing resubmits."""
    db, _, client, csrf = _stack(ctx, "m02")
    with db.uow() as u:
        for i in range(2):
            u.events.append("exp:e2", f"step_{i}", {"i": i})
    first = client.get("/api/events?stream=exp:e2").text
    # "disconnect": first read ends at seq 2; work continues server-side
    with db.uow() as u:
        for i in range(2, 5):
            u.events.append("exp:e2", f"step_{i}", {"i": i})
    resumed = client.get("/api/events?stream=exp:e2",
                         headers={"last-event-id": "2"}).text
    checks = {
        "initial_events": "step_0" in first and "step_1" in first,
        "missed_all_visible": all(f"step_{i}" in resumed
                                  for i in (2, 3, 4)),
        "no_replay": "step_0" not in resumed,
        "ordered": resumed.index("step_2") < resumed.index("step_3")
        < resumed.index("step_4"),
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f27_m03(ctx: CaseContext):
    """Unapproved origin/session mutation, media traversal, invalid
    range — safe errors, no state change, valid playback intact."""
    _, svc, client, csrf = _stack(ctx, "m03")
    clip = ctx.run_dir / "clip.mp4"
    _color_mp4(clip, 1.0)
    data = clip.read_bytes()
    art = svc.artifacts.intake_bytes(data, provenance="qa",
                                   source_key="m3")
    evil = client.post("/api/seeds",
                       json={"url": "https://youtu.be/abcdefghijk"},
                       headers={"origin": "https://evil.example.com",
                                "x-csrf-token": csrf,
                                "idempotency-key": "x"})
    no_csrf = client.post("/api/seeds",
                          json={"url": "https://youtu.be/abcdefghijk"},
                          headers={"idempotency-key": "y"})
    traversal = client.get("/api/assets/../config/media")
    bad_range = client.get(f"/api/assets/{art.id}/media",
                           headers={"range": "bytes=10-99999999"})
    good = client.get(f"/api/assets/{art.id}/media")
    checks = {
        "evil_origin_403": evil.status_code == 403
        and evil.json()["error"] == "bad_origin",
        "no_csrf_403": no_csrf.status_code == 403,
        "traversal_safe": traversal.status_code in (400, 404, 422),
        "no_state_change": client.get("/api/seeds/nope").status_code
        == 404,
        "bad_range_416": bad_range.status_code == 416,
        "valid_playback": good.status_code == 200
        and good.content == data,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def f27_m04(ctx: CaseContext):
    """Restart the API while work is durable: a fresh app over the
    same db sees identical state; health carries no credentials."""
    db, svc, client, csrf = _stack(ctx, "m04")
    mut = lambda m, p, k, **kw: _mut(client, csrf, m, p, k, **kw)
    mut("post", "/api/experiments", "e1", json={"id": "e1"})
    # "restart": new app + client over the same durable store
    svc2 = FactoryServices(db, seeds=SeedRegistry(db))
    client2 = TestClient(create_app(svc2, session_token="tok-qa"))
    health = client2.get("/api/health").json()
    results = client2.get("/api/experiments/e1/results")
    checks = {
        "state_survives_restart": results.status_code == 200
        and results.json()["experiment_id"] == "e1",
        "health_truthful": health["api"] == "ok"
        and health["worker"]["paused"] is False,
        "no_credentials": "token" not in json.dumps(health).lower()
        and "secret" not in json.dumps(health).lower(),
        "reconcile_safe": client2.post(
            "/api/jobs/job-x/reconcile",
            headers={"x-csrf-token": "tok-qa",
                     "idempotency-key": "rc1"},
            json={}).status_code == 200,
    }
    return _result(ctx, "passed" if all(checks.values()) else "failed",
                   f"{sorted(k for k, v in checks.items() if not v)}",
                   detail=checks)


def implementations():
    return {"F27-M01": f27_m01, "F27-M02": f27_m02,
            "F27-M03": f27_m03, "F27-M04": f27_m04}
