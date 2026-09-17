"""Seed registry (F09): canonical dedupe, provenance accumulation,
media attachment and readiness.

Every mutation is a new immutable revision of the Seed record —
observation history is never lost. Duplicate URL submissions merge into
one seed with both provenance observations. Readiness is derived, never
assumed: metadata-only seeds explicitly cannot pass analysis."""
import json

from ..domain.errors import ContractError
from ..domain.records import Seed
from ..store.uow import utcnow
from .urls import parse_source_url

MEDIA_JOB_KEY = "seed_media:{}"
META_JOB_KEY = "seed_metadata:{}"


def seed_id_for(platform, native_id):
    """Deterministic, ID_RE-safe identity: platform + hash of the
    case-sensitive native id."""
    if not native_id or not all(c.isalnum() or c in "_-" for c in native_id):
        raise ContractError("bad_native_id", "native_id", repr(native_id))
    import hashlib
    digest = hashlib.sha256(native_id.encode()).hexdigest()[:16]
    return f"seed-{platform}-{digest}"


class SeedRegistry:
    def __init__(self, db, artifacts=None):
        self.db = db
        self.artifacts = artifacts

    # --------------------------------------------------------- read

    def get(self, seed_id):
        row = self.db.uow().records.get("seed", seed_id)
        if row is None:
            raise ContractError("unknown_seed", "seed_id", seed_id)
        return Seed(**json.loads(row["body"]))

    def find(self, platform, native_id):
        sid = seed_id_for(platform, native_id)
        row = self.db.uow().records.get("seed", sid)
        return Seed(**json.loads(row["body"])) if row else None

    def readiness(self, seed_id):
        """Derived readiness — metadata-only is useful for discovery but
        can never pass audiovisual analysis."""
        seed = self.get(seed_id)
        blockers, actions = [], []
        if seed.evidence_status == "media_ready":
            pass
        elif seed.evidence_status == "needs_source_media":
            blockers.append("acquisition_returned_no_usable_video")
            actions.append("import_source_media")
        else:
            blockers.append("no_source_media")
            actions.append("acquire_or_import_source_media")
        if not seed.metadata_fetched_at:
            actions.append("resolve_metadata")
        return {"seed_id": seed_id, "status": seed.evidence_status,
                "analysis_ready": not blockers,
                "blockers": blockers, "actions": actions}

    # --------------------------------------------------------- write

    def submit_url(self, url, via="manual_url", observed_at=None):
        """Canonicalize + dedupe. Returns (seed, created)."""
        ref = parse_source_url(url)
        sid = seed_id_for(ref["platform"], ref["native_id"])
        obs = {"url_form": url, "via": via,
               "observed_at": observed_at or utcnow()}
        with self.db.uow() as u:
            row = u.records.get("seed", sid)
            if row is None:
                seed = Seed(schema_version="seed.v1", id=sid,
                            created_at=observed_at or utcnow(),
                            platform=ref["platform"],
                            canonical_url=ref["canonical_url"],
                            native_id=ref["native_id"],
                            original_url=url,
                            evidence_status="metadata_only",
                            provenance=[obs])
                seed.validate_or_raise()
                u.records.put(seed)
                u.events.append(f"seed:{sid}", "seed_registered",
                                {"canonical_url": ref["canonical_url"],
                                 "via": via})
                return seed, True
            seed = Seed(**json.loads(row["body"]))
            if obs not in seed.provenance:
                seed.provenance = seed.provenance + [obs]
                self._revise(u, row, seed, "provenance_observed",
                             {"via": via})
            return seed, False

    def apply_metadata(self, seed_id, metadata, fetched_at=None):
        """Store provider-observed metadata as a new revision. Caller
        decides cache policy; this never fabricates missing fields."""
        with self.db.uow() as u:
            row, seed = self._load(u, seed_id)
            seed.metadata = dict(metadata)
            seed.metadata_fetched_at = fetched_at or utcnow()
            if metadata.get("creator_id"):
                seed.creator_id = metadata["creator_id"]
            if metadata.get("title"):
                seed.title = metadata["title"]
            self._revise(u, row, seed, "metadata_observed",
                         {"fields": sorted(metadata)})
            return seed

    def mark_needs_media(self, seed_id, reason):
        with self.db.uow() as u:
            row, seed = self._load(u, seed_id)
            seed.evidence_status = "needs_source_media"
            self._revise(u, row, seed, "needs_source_media",
                         {"reason": reason})
            return seed

    def attach_media(self, seed_id, artifact_id, via="seed_source"):
        """Attach a verified artifact as the seed's source media, then
        satisfy the seed_media job and promote blocked dependents."""
        with self.db.uow() as u:
            row, seed = self._load(u, seed_id)
            art = u.artifacts.get(artifact_id)
            if art is None:
                raise ContractError("unknown_artifact", "artifact_id",
                                    artifact_id)
            if art["kind"] != "video":
                raise ContractError("not_video", "artifact_id",
                                    f"probed kind={art['kind']}")
            seed.source_asset_id = artifact_id
            seed.evidence_status = "media_ready"
            self._revise(u, row, seed, "media_attached",
                         {"artifact_id": artifact_id, "via": via})
            job = u.jobs.by_logical_key(MEDIA_JOB_KEY.format(seed_id))
            promoted = []
            if job and job["status"] not in ("succeeded", "cancelled"):
                u.conn.execute(
                    "UPDATE jobs SET status='succeeded', blocked_reason=NULL,"
                    " updated_at=?, version=version+1 WHERE id=?",
                    (utcnow(), job["id"]))
                u.events.append(f"job:{job['id']}", "succeeded",
                                {"via": via})
                promoted = self._unblock_and_promote(u, job["id"])
            return seed, promoted

    def import_manual(self, seed_id, path, via="manual_import",
                      provenance_detail=""):
        """Manual upload/local import: real F04 intake (probe-verified
        video), then resume the seed's blocked analysis dependencies."""
        if self.artifacts is None:
            raise ContractError("no_artifact_store", "artifacts")
        seed = self.get(seed_id)
        artifact = self.artifacts.intake_file(
            path, provenance="manual",
            source_key=seed.canonical_url or seed.id,
            source_detail=provenance_detail or via,
            requested_kind="video")
        return self.attach_media(seed_id, artifact.id, via=via)

    # ------------------------------------------------------- internals

    def _load(self, u, seed_id):
        row = u.records.get("seed", seed_id)
        if row is None:
            raise ContractError("unknown_seed", "seed_id", seed_id)
        return row, Seed(**json.loads(row["body"]))

    def _revise(self, u, row, seed, event, body):
        seed.revision = row["revision"] + 1
        seed.validate_or_raise()
        u.records.put(seed)          # new immutable revision row
        u.events.append(f"seed:{seed.id}", event, body)

    def _unblock_and_promote(self, u, job_id):
        """Descendants blocked on this job return to the ready path."""
        rows = {r["id"]: r for r in u.conn.execute(
            "SELECT id, depends_on, status FROM jobs").fetchall()}
        children = {}
        for jid, r in rows.items():
            for d in json.loads(r["depends_on"] or "[]"):
                children.setdefault(d, []).append(jid)
        stack, promoted = [job_id], []
        while stack:
            cur = stack.pop()
            for child in children.get(cur, []):
                r = rows[child]
                if r["status"] == "blocked":
                    u.conn.execute(
                        "UPDATE jobs SET status='waiting_dependencies',"
                        " blocked_reason=NULL, updated_at=? WHERE id=?",
                        (utcnow(), child))
                    promoted.append(child)
                stack.append(child)
        # Promote anything whose deps are now all succeeded.
        for r in u.conn.execute(
                "SELECT id, depends_on FROM jobs WHERE "
                "status='waiting_dependencies'").fetchall():
            if all((u.conn.execute(
                    "SELECT status FROM jobs WHERE id=?",
                    (d,)).fetchone() or {"status": ""})["status"]
                    == "succeeded"
                    for d in json.loads(r["depends_on"] or "[]")):
                u.conn.execute(
                    "UPDATE jobs SET status='ready', updated_at=? "
                    "WHERE id=?", (utcnow(), r["id"]))
        return promoted
