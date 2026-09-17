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
from modules.factory.bootstrap import bootstrap
from test_factory_application import application, prepare, quote_and_run


@pytest.fixture
def env(tmp_path):
    services = bootstrap(tmp_path)
    db = services.db
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


def test_stale_revision_conflict(application):
    s,c,act,w,root=application; prepare(application)
    r=act('patch','/api/experiments/fixture-exp/draft',{'reason':'edit'},rev=5)
    assert r.status_code==409 and r.json()['error']=='stale_revision'
    r=act('patch','/api/experiments/fixture-exp/draft',{'reason':'edit'},rev=1)
    assert r.json()['draft']['revision']==2


def test_quote_authorize_run_flow(application):
    s,c,act,w,root=application; prepare(application)
    plan=quote_and_run(application)
    assert plan['total_price']=={}  # imported footage has no invented price
    assert s.db.uow().jobs.get('run-fixture-exp-r1')


def test_authorize_wrong_revision(application):
    s,c,act,w,root=application; prepare(application)
    r=act('post','/api/experiments/fixture-exp/authorize',{},rev=0)
    assert r.status_code==409 and r.json()['error']=='stale_revision'


def test_run_requires_authorization(application):
    s,c,act,w,root=application; prepare(application)
    act('post','/api/experiments/fixture-exp/quote',{},rev=1);w.tick()
    r=act('post','/api/experiments/fixture-exp/run',{},rev=1)
    assert r.status_code==409 and r.json()['error']=='not_authorized'


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
    assert r.status_code == 206 and r.content == data[-1:]
    r = client.get(f"/api/assets/{aid}/media",headers={"range":"bytes=-10"})
    assert r.status_code == 206 and r.content == data[-10:]
    r = client.get(f"/api/assets/{aid}/media",headers={"range":"bytes=-0"})
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


def test_material_edit_invalidates_quote_and_authorization(application):
    s,c,act,w,root=application; body,art=prepare(application)
    act('post','/api/experiments/fixture-exp/quote',{},rev=1);w.tick()
    plan=s.plan_for('fixture-exp')
    act('post','/api/experiments/fixture-exp/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'test'},rev=1)
    edit=act('patch','/api/experiments/fixture-exp/draft',{'segments':body['segments'],'reason':'new cut'},rev=1)
    assert edit.status_code==200
    r=act('post','/api/experiments/fixture-exp/run',{},rev=2)
    assert r.json()['error']=='no_quote'
    r=act('post','/api/experiments/fixture-exp/authorize',{'plan_hash':plan['plan_hash'],'reviewer':'test'},rev=2)
    assert r.json()['error']=='no_quote'


def test_same_size_import_with_different_bytes_is_a_conflict(env):
    from modules.factory.audio import pcm
    client, csrf, *_ = env
    a = pcm.write_wav(pcm.sine(0.2, freq=440))
    b = pcm.write_wav(pcm.sine(0.2, freq=880))
    assert len(a) == len(b)
    r = mut(client, csrf, "post", "/api/imports", key="upload", content=a, headers={"x-filename": "sample.wav"})
    assert r.status_code == 201
    r = mut(client, csrf, "post", "/api/imports", key="upload", content=b, headers={"x-filename": "sample.wav"})
    assert r.status_code == 409
    assert r.json()["error"] == "idempotency_conflict"
