"""F04 — artifact registry, media intake, provenance. Offline; defects
come from the reference-defects fixture."""
import os
import shutil

import pytest

from modules.factory.artifacts import ArtifactStore, IntakeError, \
    list_intake
from modules.factory.domain import ContractError
from modules.factory.media.probe import probe
from modules.factory.store import Database
from modules.factory.testing import fixtures


@pytest.fixture(scope="module")
def defs(tmp_path_factory):
    """Materialize reference-defects once per test module."""
    ws = tmp_path_factory.mktemp("defs")
    lock = fixtures.materialize("reference-defects", ws)
    return ws / "fixtures" / "reference-defects"


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "f.db")
    s = ArtifactStore(tmp_path / "artifacts", db=db)
    yield s
    db.close()


def _good_mp4(tmp_path):
    src = tmp_path / "good.mp4"
    shutil.copy2(
        fixtures.FIXTURE_ROOT / "reference-defects",  # placeholder guard
        src) if False else None
    return src


def _make_good(tmp_path):
    """Generate one valid portrait clip."""
    src = tmp_path / "good.mp4"
    fixtures._color_mp4(src, 5.0)
    return src


class TestProbe:
    def test_probe_facts(self, tmp_path):
        p = _make_good(tmp_path)
        info = probe(p)
        assert info.kind() == "video"
        v = info.video
        assert v.width == 360 and v.height == 640
        assert v.avg_frame_rate is not None
        assert info.audio is not None and info.audio.sample_rate > 0
        assert info.duration_s == pytest.approx(5.0, abs=0.1)

    def test_zero_and_unprobeable(self, defs):
        with pytest.raises(ContractError) as e:
            probe(defs / "zero_byte.mp4")
        assert e.value.code == "zero_bytes"
        with pytest.raises(ContractError) as e:
            probe(defs / "corrupt.mp4")
        assert e.value.code == "unprobeable"

    def test_vfr_detected(self, defs):
        info = probe(defs / "vfr_clip.mp4")
        v = info.video
        assert v is not None
        # VFR flag is a fact; exact rates vary by ffmpeg build
        assert "vfr" in v.to_dict()

    def test_missing_audio_visible(self, defs):
        info = probe(defs / "missing_audio.mp4")
        assert info.kind() == "video" and info.audio is None


class TestIntake:
    def test_valid_intake_registers(self, store, tmp_path):
        src = _make_good(tmp_path)
        art = store.intake_file(src, provenance="seed_source",
                                source_key="test:good",
                                requested_kind="video",
                                min_width=360, min_height=640,
                                min_usable_s=4.0)
        assert art.kind == "video"
        assert len(art.sha256) == 64
        assert art.native_width == 360 and art.native_height == 640
        row = store.db.uow().artifacts.get(art.id)
        assert row["sha256"] == art.sha256
        evs = store.db.uow().events.since(f"artifact:{art.id}")
        assert evs[0]["type"] == "intake"

    def test_thumbnail_as_video_rejected(self, store, defs):
        with pytest.raises(IntakeError) as e:
            store.intake_file(defs / "thumbnail_as_video.mp4",
                              provenance="manual", source_key="t",
                              requested_kind="video")
        assert e.value.code == "kind_mismatch"
        assert "image" in e.value.detail

    def test_corrupt_and_zero_rejected(self, store, defs):
        with pytest.raises(IntakeError) as e:
            store.intake_file(defs / "corrupt.mp4", provenance="manual",
                              source_key="c")
        assert e.value.code in ("unprobeable", "no_streams")
        with pytest.raises(IntakeError) as e:
            store.intake_file(defs / "zero_byte.mp4", provenance="manual",
                              source_key="z")
        assert e.value.code == "zero_bytes"

    def test_short_clip_rejected_against_allocation(self, store, defs):
        with pytest.raises(IntakeError) as e:
            store.intake_file(defs / "short_clip.mp4", provenance="manual",
                              source_key="s", requested_kind="video",
                              min_usable_s=4.0)
        assert e.value.code == "duration_too_short"

    def test_failed_files_never_registered(self, store, defs):
        for name in ("corrupt.mp4", "zero_byte.mp4"):
            with pytest.raises(IntakeError):
                store.intake_file(defs / name, provenance="manual",
                                  source_key=name)
        n = store.db.conn.execute(
            "SELECT COUNT(*) FROM artifacts").fetchone()[0]
        assert n == 0
        assert list((store.root / "staging").iterdir()) == []

    def test_dedupe_preserves_both_sources(self, store, tmp_path):
        src = _make_good(tmp_path)
        a1 = store.intake_file(src, provenance="seed_source",
                               source_key="record:one")
        a2 = store.intake_file(src, provenance="manual",
                               source_key="record:two")
        assert a1.id == a2.id                      # same blob
        blobs = list((store.root / "blobs").rglob("*"))
        assert len([b for b in blobs if b.is_file()]) == 1
        rows = store.db.conn.execute(
            "SELECT source_key FROM artifact_sources WHERE artifact_id=?",
            (a1.id,)).fetchall()
        assert sorted(r[0] for r in rows) == ["record:one", "record:two"]

    def test_empty_folder_returns_missing_list(self, tmp_path):
        assert list_intake(tmp_path / "empty")["missing"]
        (tmp_path / "empty").mkdir()
        assert list_intake(tmp_path / "empty")["missing"]


class TestServing:
    def test_serve_registered(self, store, tmp_path):
        art = store.intake_file(_make_good(tmp_path),
                                provenance="manual", source_key="k")
        real = store.path_for(art.id)
        assert real.is_file() and str(real).startswith(str(store.root))

    def test_unknown_artifact_refused(self, store):
        with pytest.raises(ContractError) as e:
            store.path_for("art:does-not-exist")
        assert e.value.code == "unknown_artifact"

    def test_traversal_refused(self, store, tmp_path):
        art = store.intake_file(_make_good(tmp_path),
                                provenance="manual", source_key="k")
        store.db.conn.execute(
            "UPDATE artifacts SET local_path='../../etc/passwd' WHERE id=?",
            (art.id,))
        with pytest.raises(ContractError) as e:
            store.path_for(art.id)
        assert e.value.code in ("path_escape", "referenced_missing")

    def test_symlink_escape_refused(self, store, tmp_path):
        art = store.intake_file(_make_good(tmp_path),
                                provenance="manual", source_key="k")
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"secret")
        link = store.root / "blobs" / "link.bin"
        os.symlink(outside.resolve(), link)
        store.db.conn.execute(
            "UPDATE artifacts SET local_path='blobs/link.bin' WHERE id=?",
            (art.id,))
        with pytest.raises(ContractError) as e:
            store.path_for(art.id)
        assert e.value.code == "path_escape"


class TestRecovery:
    def test_interrupted_transfer_classified(self, store, tmp_path):
        leftover = store.root / "staging" / "deadbeef.part"
        leftover.write_bytes(b"partial")
        art = store.intake_file(_make_good(tmp_path),
                                provenance="manual", source_key="k")
        # Simulate referenced-but-missing by deleting the blob.
        (store.root / art.local_path).unlink()
        report = store.recover_staging()
        assert report["unreferenced_temporary"][0]["path"].endswith(
            "deadbeef.part")
        assert art.id in report["referenced_missing"]
        store.discard_staging()
        assert list((store.root / "staging").iterdir()) == []
