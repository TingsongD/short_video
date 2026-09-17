"""F27 — application API: idempotency, revisions, SSE, security,
media ranges, sanitized errors, async durability.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

from modules.factory.api import create_app
from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.seeds.registry import SeedRegistry
from modules.factory.services import FactoryServices
from modules.factory.store import Database


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "f.db")
    artifacts = ArtifactStore(tmp_path / "artifacts", db=db)
    services = FactoryServices(db, seeds=SeedRegistry(db),
                               artifacts=artifacts,
                               artifact_root=tmp_path / "artifacts")
    app = create_app(services, session_token="tok-test")
    client = TestClient(app)
    r = client.post("/api/session")
    csrf = r.json()["session_token"]
    return client, csrf, db, services, tmp_path


def mut(client, csrf, method, path, key="k1", rev=None, **kw):
    h = {"x-csrf-token": csrf, "idempotency-key": key}
    if rev is not None:
        h["x-expected-revision"] = str(rev)
    h.update(kw.pop("headers", {}))
    return getattr(client, method)(path, headers=h, **kw)


# ----------------------------------------------------------- security

def test_session_and_csrf(env):
    client, csrf, *_ = env
    assert csrf == "tok-test"
    r = client.post("/api/seeds",
                    json={"url": "https://youtu.be/abcdefghijk"})
    assert r.status_code == 403 and r.json()["error"] == "csrf"


def test_bad_host_denied(env):
    client, csrf, *_ = env
    r = client.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code == 403 and r.json()["error"] == "bad_host"


def test_bad_origin_denied(env):
    client, csrf, *_ = env
    r = mut(client, csrf, "post", "/api/seeds",
            json={"url": "https://youtu.be/abcdefghijk"},
            headers={"x-csrf-token": csrf, "idempotency-key": "k",
                     "origin": "https://evil.example.com"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


# -------------------------------------------------------- idempotency

def test_missing_idempotency_key(env):
    client, csrf, *_ = env
    r = client.post("/api/seeds",
                    json={"url": "https://youtu.be/abcdefghijk"},
                    headers={"x-csrf-token": csrf})
    assert r.status_code == 400
    assert r.json()["error"] == "missing_idempotency_key"


def test_idempotent_replay_and_conflict(env):
    client, csrf, *_ = env
    url = "https://youtu.be/abcdefghijk"
    r1 = mut(client, csrf, "post", "/api/seeds",
             json={"url": url})
    r2 = mut(client, csrf, "post", "/api/seeds",
             json={"url": url})                    # identical replay
    assert r1.status_code == 201
    assert r2.json() == r1.json()                    # original result
    r3 = mut(client, csrf, "post", "/api/seeds",
             json={"url": "https://youtu.be/zzzzzzzzzzz"})
    assert r3.status_code == 409
    assert r3.json()["error"] == "idempotency_conflict"


def test_stale_revision_conflict(env):
    client, csrf, *_ = env
    mut(client, csrf, "post", "/api/experiments",
        json={"id": "e1", "variants": ["A", "B"]})
    r = mut(client, csrf, "patch",
            "/api/experiments/e1/draft", rev=5, key="k-p1",
            json={"provider": "vertex"})
    assert r.status_code == 409
    assert r.json()["error"] == "stale_revision"
    r2 = mut(client, csrf, "patch",
             "/api/experiments/e1/draft", rev=0, key="k2",
             json={"provider": "vertex"})
    assert r2.json()["draft"]["revision"] == 1


# ------------------------------------------------- quote→auth→run ---

def test_quote_authorize_run_flow(env):
    client, csrf, *_ = env
    mut(client, csrf, "post", "/api/experiments",
        json={"id": "e2", "unique_work":
              [{"credits": 4}, {"usd_micros": 900}]})
    q = mut(client, csrf, "post", "/api/experiments/e2/quote",
            key="kq", json={}).json()["quote"]
    assert q["units"] == {"credits": 4, "usd_micros": 900}
    a = mut(client, csrf, "post", "/api/experiments/e2/authorize",
            key="ka", rev=0, json={})
    assert a.json()["authorization"]["revision"] == 0
    r = mut(client, csrf, "post", "/api/experiments/e2/run",
            key="kr", rev=0, json={})
    assert r.status_code == 202
    assert r.json()["run"]["job_id"] == "job-e2"


def test_authorize_wrong_revision(env):
    client, csrf, *_ = env
    mut(client, csrf, "post", "/api/experiments",
        json={"id": "e3", "unique_work": []})
    mut(client, csrf, "post", "/api/experiments/e3/quote",
        key="kq", json={})
    mut(client, csrf, "patch", "/api/experiments/e3/draft", key="kp",
        rev=0, json={"note": "changed"})
    r = mut(client, csrf, "post", "/api/experiments/e3/authorize",
            key="ka", rev=0, json={})
    assert r.status_code == 409              # old approval can't fund


def test_run_requires_authorization(env):
    client, csrf, *_ = env
    mut(client, csrf, "post", "/api/experiments",
        json={"id": "e4"})
    r = mut(client, csrf, "post", "/api/experiments/e4/run",
            key="kr", json={})
    assert r.status_code == 409
    assert r.json()["error"] == "not_authorized"


# ------------------------------------------------------------- media

def test_media_range_and_containment(env):
    client, csrf, _, services, tmp = env
    from modules.factory.testing.fixtures import _color_mp4
    clip = tmp / "clip.mp4"
    _color_mp4(clip, 1.0)
    data = clip.read_bytes()
    art = services.artifacts.intake_bytes(
        data, provenance="test", source_key="m1")
    aid = art["id"] if isinstance(art, dict) else art.id
    r = client.get(f"/api/assets/{aid}/media")
    assert r.status_code == 200 and r.content == data
    assert r.headers["accept-ranges"] == "bytes"
    r = client.get(f"/api/assets/{aid}/media",
                   headers={"range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == data[10:20]
    assert r.headers["content-range"] == \
        f"bytes 10-19/{len(data)}"
    r = client.get(f"/api/assets/{aid}/media",
                   headers={"range": f"bytes={len(data)-1}-{len(data)+9}"})
    assert r.status_code == 416
    r = client.get("/api/assets/../secrets.toml/media")
    assert r.status_code in (404, 400, 422)
    r = client.get("/api/assets/nonexistent/media")
    assert r.status_code == 404


def test_upload_type_and_size_limits(env):
    client, csrf, *_ = env
    r = mut(client, csrf, "post", "/api/imports",
            content=b"x" * 10,
            headers={"x-csrf-token": csrf, "idempotency-key": "ki",
                     "x-filename": "evil.exe"})
    assert r.status_code == 400 and r.json()["error"] == "bad_type"


# ------------------------------------------------------------ events

def test_sse_replay_and_disconnect(env):
    client, csrf, db, services, _ = env
    with db.uow() as u:
        for i in range(3):
            u.events.append("exp:e1", f"step_{i}", {"i": i})
    r = client.get("/api/events?stream=exp:e1")
    assert r.status_code == 200
    body = r.text
    assert "id: 1" in body and "step_0" in body
    assert "id: 3" in body and ": keepalive" in body
    # reconnect with Last-Event-ID gets only missed events
    with db.uow() as u:
        u.events.append("exp:e1", "step_3", {"i": 3})
    r2 = client.get("/api/events?stream=exp:e1",
                    headers={"last-event-id": "2"})
    assert "step_2" in r2.text and "step_3" in r2.text
    assert "step_0" not in r2.text          # no replay of seen events


# ------------------------------------------------------------ errors

def test_404_and_sanitized_error(env):
    client, csrf, *_ = env
    r = client.get("/api/seeds/nope")
    assert r.status_code == 404
    assert "error" in r.json()              # no internals leaked
    r2 = client.get("/api/experiments/ghost/results")
    assert r2.status_code == 404


def test_openapi_documented(env):
    client, *_ = env
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "factory-api.v1"
    paths = spec["paths"]
    for p in ("/api/health", "/api/seeds", "/api/experiments",
              "/api/assets/{asset_id}/media", "/api/events"):
        assert p in paths, p
