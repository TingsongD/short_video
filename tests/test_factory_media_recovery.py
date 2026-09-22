"""Offline previews must not use a cross-thread shared SQLite connection."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from modules.factory.api import create_app
from modules.factory.testing.fixtures import _color_mp4
from test_factory_api import env


def clip(services, tmp):
    source = tmp / "preview.mp4"
    _color_mp4(source, 0.3)
    return services.artifacts.intake_file(source, "test", "preview"), source.read_bytes()


def test_concurrent_previews_use_independent_database_reads(env):
    _, _, db, services, tmp = env
    art, data = clip(services, tmp)
    # SQLite itself enforces ownership: the API/background threads cannot
    # borrow this main-thread connection, even with simultaneous previews.
    db.conn.close()
    db.conn = sqlite3.connect(db.path, check_same_thread=True)
    db.conn.row_factory = sqlite3.Row
    app = create_app(services)
    def preview(index):
        with TestClient(app) as client:
            return client.get(f"/api/assets/{art.id}/media", headers={"range": f"bytes={index}-{index+9}"})
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(preview, range(18)))
        for index, result in enumerate(results):
            assert result.status_code == 206
            assert result.content == data[index:index+10]
    finally:
        db.close()


@pytest.mark.parametrize("damage,error,status", [
    ("record", "unknown_artifact", 404),
    ("file", "referenced_missing", 400),
    ("bytes", "artifact_changed", 400),
])
def test_unavailable_or_changed_preview_is_typed_not_500(env, damage, error, status):
    client, _, db, services, tmp = env
    art, _ = clip(services, tmp)
    path = services.artifacts.path_for(art.id)
    if damage == "record":
        with db.uow() as u:
            u.conn.execute("DELETE FROM artifact_sources WHERE artifact_id=?", (art.id,))
            u.conn.execute("DELETE FROM artifacts WHERE id=?", (art.id,))
    elif damage == "file":
        path.unlink()
    else:
        path.write_bytes(b"changed")
    response = client.get(f"/api/assets/{art.id}/media")
    assert response.status_code == status
    assert response.json()["error"] == error


def test_record_disappearing_during_verification_uses_one_snapshot(env, monkeypatch):
    client, _, db, services, tmp = env
    art, data = clip(services, tmp)
    path = services.artifacts.path_for(art.id)
    is_file = Path.is_file
    deleted = []
    def concurrent_removal(candidate):
        exists = is_file(candidate)
        if candidate == path and not deleted:
            # Storage-boundary fault: a separate writer removes registration
            # after containment checked it, before the old second lookup.
            with sqlite3.connect(db.path) as writer:
                writer.execute("DELETE FROM artifact_sources WHERE artifact_id=?", (art.id,))
                writer.execute("DELETE FROM artifacts WHERE id=?", (art.id,))
            deleted.append(True)
        return exists
    monkeypatch.setattr(Path, "is_file", concurrent_removal)
    response = client.get(f"/api/assets/{art.id}/media")
    assert deleted and response.status_code == 200
    assert response.content == data
    assert client.get(f"/api/assets/{art.id}/media").status_code == 404
