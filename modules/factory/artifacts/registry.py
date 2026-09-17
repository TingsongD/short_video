"""Artifact registry (F04): stage → hash → probe → validate → atomically
promote → register. Bytes dedupe by SHA-256 while distinct source
attributions are preserved; serving is by artifact ID with containment
checks, never by caller-supplied paths.

Layout under <root>:
  blobs/<sha[:2]>/<sha256>     content-addressed originals
  derived/<sha[:2]>/<sha256>/<variant>  transformed versions
  staging/<uuid>               uncommitted imports (recoverable)
"""
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import Artifact
from ..media.probe import probe
from ..store.uow import utcnow

CHUNK = 1 << 20


class IntakeError(ContractError):
    """Rejection with an actionable reason code."""


class ArtifactStore:
    def __init__(self, root, db=None):
        self.root = Path(root).resolve()
        self.db = db
        if db is not None:
            db.conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES"
                            "('artifact_root',?)", (str(self.root),))
        for sub in ("blobs", "staging", "derived"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- intake

    def intake_file(self, src, provenance, source_key, source_detail="",
                    requested_kind=None, min_width=0, min_height=0,
                    min_usable_s=0.0, created_at=None):
        src = Path(src)
        if not src.is_file():
            raise IntakeError("missing_source", "src", str(src))
        staged = self.root / "staging" / f"{uuid.uuid4().hex}.part"
        sha = hashlib.sha256()
        byte_count = 0
        try:
            with open(src, "rb") as fin, open(staged, "wb") as fout:
                while chunk := fin.read(CHUNK):
                    sha.update(chunk)
                    byte_count += len(chunk)
                    fout.write(chunk)
        except OSError:
            staged.unlink(missing_ok=True)
            raise
        return self._complete(staged, sha.hexdigest(), byte_count,
                              provenance, source_key, source_detail,
                              requested_kind, min_width, min_height,
                              min_usable_s, created_at)

    def intake_bytes(self, data, provenance, source_key, source_detail="",
                     requested_kind=None, **checks):
        staged = self.root / "staging" / f"{uuid.uuid4().hex}.part"
        staged.write_bytes(data)
        return self._complete(staged, hashlib.sha256(data).hexdigest(),
                              len(data), provenance, source_key,
                              source_detail, requested_kind,
                              checks.get("min_width", 0),
                              checks.get("min_height", 0),
                              checks.get("min_usable_s", 0.0), None)

    def _complete(self, staged, sha256, byte_count, provenance, source_key,
                  source_detail, requested_kind, min_width, min_height,
                  min_usable_s, created_at):
        try:
            info = probe(staged)
        except ContractError as e:
            staged.unlink(missing_ok=True)
            raise IntakeError(e.code, e.field, e.detail)
        kind = info.kind()
        if kind == "unknown":
            staged.unlink(missing_ok=True)
            raise IntakeError("no_streams", "src", "no A/V/image streams")
        if requested_kind and kind != requested_kind:
            staged.unlink(missing_ok=True)
            raise IntakeError(
                "kind_mismatch", "src",
                f"requested {requested_kind}, probed {kind} "
                f"({info.format_name})")
        v = info.video
        if kind == "video":
            if min_width and (v.width < min_width or v.height < min_height):
                staged.unlink(missing_ok=True)
                raise IntakeError("resolution_too_small", "src",
                                  f"{v.width}x{v.height} < "
                                  f"{min_width}x{min_height}")
            if min_usable_s and info.duration_s < min_usable_s:
                staged.unlink(missing_ok=True)
                raise IntakeError("duration_too_short", "src",
                                  f"{info.duration_s:.2f}s < "
                                  f"{min_usable_s}s usable")
        blob = self._promote(staged, sha256)
        artifact = Artifact(
            schema_version="artifact.v1",
            id=f"art:{sha256[:16]}",
            created_at=created_at or utcnow(),
            sha256=sha256, kind=kind, byte_count=byte_count,
            probe=info.to_dict(), provenance=provenance,
            local_path=str(blob.relative_to(self.root)),
            native_width=v.width if v else 0,
            native_height=v.height if v else 0,
            native_fps_num=(v.avg_frame_rate.numerator
                            if v and v.avg_frame_rate else 0),
            native_fps_den=(v.avg_frame_rate.denominator
                            if v and v.avg_frame_rate else 1))
        if self.db:
            with self.db.uow() as u:
                existing = u.artifacts.get(artifact.id)
                if existing is None:
                    u.artifacts.register(artifact)
                u.conn.execute(
                    "INSERT OR IGNORE INTO artifact_sources(artifact_id,"
                    "source_key,detail,created_at) VALUES(?,?,?,?)",
                    (artifact.id, source_key, source_detail,
                     artifact.created_at))
                u.events.append(f"artifact:{artifact.id}", "intake", {
                    "source_key": source_key, "sha256": sha256,
                    "provenance": provenance,
                    "deduplicated": existing is not None})
        return artifact

    def _promote(self, staged, sha256):
        """Atomic promotion into content-addressed storage. Duplicate
        bytes reuse the existing blob — distinct source records still get
        their own artifact rows."""
        blob = (self.root / "blobs" / sha256[:2] / sha256)
        if blob.exists():
            staged.unlink(missing_ok=True)
            return blob
        blob.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, blob)       # atomic on same filesystem
        return blob

    def add_derived(self, source_sha256, variant, path, metadata):
        """Register a derived version alongside original bytes; native
        facts stay on the original artifact."""
        src = Path(path)
        if not src.is_file():
            raise IntakeError("missing_source", "derived", str(path))
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        dest = (self.root / "derived" / source_sha256[:2] / source_sha256
                / variant)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            os.replace(src, dest)
        else:
            src.unlink(missing_ok=True)
        return {"derived_from": source_sha256, "variant": variant,
                "sha256": sha, "path": str(dest.relative_to(self.root)),
                "metadata": metadata}

    # --------------------------------------------------------- serving

    def path_for(self, artifact_id):
        """Resolve a registered artifact to a contained real path."""
        if self.db is None:
            raise ContractError("no_registry", "db")
        row = self.db.uow().artifacts.get(artifact_id)
        if row is None:
            raise ContractError("unknown_artifact", "artifact_id",
                                artifact_id)
        rel = row["local_path"]
        real = (self.root / rel).resolve()
        if not str(real).startswith(str(self.root) + os.sep):
            raise ContractError("path_escape", "local_path", rel)
        if not real.is_file():
            raise ContractError("referenced_missing", "local_path", rel)
        return real

    def verified_path(self, artifact_id):
        path = self.path_for(artifact_id)
        row = self.db.uow().artifacts.get(artifact_id)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(CHUNK), b""):
                digest.update(chunk)
        if path.stat().st_size != row["byte_count"] or digest.hexdigest() != row["sha256"]:
            raise ContractError("artifact_changed", "artifact_id", artifact_id)
        return path

    # -------------------------------------------------------- recovery

    def recover_staging(self):
        """Classify leftovers after an interrupted transfer."""
        orphans = []
        for f in (self.root / "staging").iterdir():
            if f.name.endswith(".part"):
                orphans.append({"path": str(f), "bytes": f.stat().st_size,
                                "classification": "unreferenced_temporary"})
        missing = []
        if self.db:
            for row in self.db.uow().artifacts.missing():
                missing.append(row["id"])
            for row in self.db.conn.execute(
                    "SELECT id, local_path FROM artifacts").fetchall():
                real = (self.root / row["local_path"]).resolve()
                if not real.is_file():
                    missing.append(row["id"])
        return {"unreferenced_temporary": orphans,
                "referenced_missing": sorted(set(missing))}

    def discard_staging(self):
        for f in (self.root / "staging").iterdir():
            if f.name.endswith(".part"):
                f.unlink()

    def refs(self, artifact_id):
        if self.db is None:
            return 0
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM artifact_links WHERE artifact_id=?",
            (artifact_id,)).fetchone()
        return row[0] if row else 0


def list_intake(folder, requested_kind=None):
    """Empty folder → explicit missing list, never an exception."""
    p = Path(folder)
    if not p.is_dir():
        return {"missing": True, "candidates": []}
    files = [f for f in sorted(p.iterdir()) if f.is_file()]
    return {"missing": not files, "candidates": [str(f) for f in files]}
