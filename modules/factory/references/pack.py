"""Reference pack assembly (F18): product/variant + presenter visual
references with provenance, validation, hash-pinned acceptance and
explicit replacement. Product images stay separate from style/scene.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import (PresenterIdentity, ReferencePack,
                              VisualReference, content_hash)

PRODUCT_ROLES = {"product_front", "product_back", "product_detail"}
PRESENTER_ROLES = {"presenter_headshot", "presenter_full"}


def pack_hash(selection):
    """selection: {role: artifact_sha256} — the identity downstream
    picture jobs bind to."""
    return content_hash({r: selection[r] for r in sorted(selection)})


class ReferencePackService:
    def __init__(self, db, artifacts):
        self.db = db
        self.artifacts = artifacts      # ArtifactRegistry (F04)

    # ----------------------------------------------------- presenters

    def create_presenter(self, pid, guide, provenance, kind="fictional",
                         now=""):
        p = PresenterIdentity(schema_version="presenter.v1", id=pid,
                              created_at=now, kind=kind, guide=guide,
                              provenance=provenance)
        p.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(p)
        return p

    # ---------------------------------------------------------- packs

    def create_pack(self, pack_id, product_id, variant_id="",
                    presenter_id="", snapshot_id="", plan_hash="",
                    required_roles=None, now=""):
        pack = ReferencePack(
            schema_version="reference_pack.v1", id=pack_id,
            created_at=now, product_snapshot_id=snapshot_id,
            product_id=product_id, variant_id=variant_id,
            presenter_id=presenter_id, plan_hash=plan_hash,
            required_roles=list(required_roles
                                or ["product_front"]))
        pack.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(pack)
        return pack

    def from_snapshot(self, pack_id, snapshot_id, presenter_id="",
                      plan_hash="", now=""):
        """Seed product refs from an F11 snapshot's media artifacts."""
        snap = self._get("productsnapshot", snapshot_id)
        if snap is None:
            raise ContractError("unknown_snapshot", "id", snapshot_id)
        pack = self.create_pack(
            pack_id, snap["product_id"], snap.get("variant_id", ""),
            presenter_id, snapshot_id, plan_hash, now=now)
        refs = []
        for i, aid in enumerate(snap.get("media_artifact_ids") or []):
            art = self._artifact(aid)
            if art is None or art["kind"] != "image":
                continue
            role = "product_front" if i == 0 else "product_detail"
            refs.append(self.add_reference(
                pack_id, f"ref-{pack_id}-{i}", role, aid,
                origin="product_snapshot",
                variant_id=snap.get("variant_id", ""),
                source_artifact_ids=[aid], now=now))
        return pack, refs

    # ----------------------------------------------------- references

    def add_reference(self, pack_id, ref_id, role, artifact_id,
                      origin="manual_import", variant_id="",
                      attributes=None, source_artifact_ids=None,
                      generation_attempt_id="", now=""):
        self._require_pack(pack_id)
        art = self._artifact(artifact_id)
        if art is None:
            raise ContractError("unknown_artifact", "artifact_id",
                                artifact_id)
        if art["kind"] != "image":
            raise ContractError("reference_not_image", "artifact_id",
                                art["kind"])
        ref = VisualReference(
            schema_version="visual_reference.v1", id=ref_id,
            created_at=now, pack_id=pack_id, role=role, origin=origin,
            artifact_id=artifact_id, artifact_sha256=art["sha256"],
            source_artifact_ids=list(source_artifact_ids or []),
            variant_id=variant_id, attributes=dict(attributes or {}),
            acceptance={"state": "pending", "reviewer": "",
                        "reasons": [], "limits": [], "reviewed_hash": ""},
            generation_attempt_id=generation_attempt_id)
        ref.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(ref)
        return ref

    def get(self, ref_id):
        return self._get("visualreference", ref_id)

    def pack_refs(self, pack_id, status=None):
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='visualreference'"
            " AND revision=(SELECT MAX(revision) FROM records r2"
            "  WHERE r2.kind='visualreference' AND r2.id=records.id)"
        ).fetchall()
        out = []
        for row in rows:
            body = json.loads(row["body"])
            if body.get("pack_id") != pack_id:
                continue
            if status and body.get("status") != status:
                continue
            out.append(body)
        return out

    # ------------------------------------------------------ selection

    def selection(self, pack_id):
        """{role: artifact_sha256} for accepted refs — variant-shared
        while locked variables are unchanged."""
        sel = {}
        for ref in self.pack_refs(pack_id, status="accepted"):
            sel[ref["role"]] = ref["artifact_sha256"]
        return sel

    def refresh_pack_hash(self, pack_id):
        pack = self._require_pack(pack_id)
        sel = self.selection(pack_id)
        missing = [r for r in pack["required_roles"] if r not in sel]
        status = "ready" if not missing else "assembling"
        self._update_pack(pack_id, pack_hash=pack_hash(sel) if sel else "",
                          status=status)
        return {"pack_hash": pack_hash(sel) if sel else "",
                "missing_roles": missing, "status": status}

    # --------------------------------------------------- replace/stale

    def replace(self, ref_id, new_artifact_id, reviewer=""):
        """Explicit replacement: old revision superseded, new pending
        revision created; dependents must be re-pinned by the caller."""
        old = self._get("visualreference", ref_id)
        if old is None:
            raise ContractError("unknown_reference", "id", ref_id)
        art = self._artifact(new_artifact_id)
        if art is None or art["kind"] != "image":
            raise ContractError("reference_not_image", "artifact_id")
        new = dict(old)
        new["revision"] = old["revision"] + 1
        new["artifact_id"] = new_artifact_id
        new["artifact_sha256"] = art["sha256"]
        new["status"] = "pending"
        new["parent_hash"] = old["artifact_sha256"]
        new["acceptance"] = {"state": "pending", "reviewer": "",
                             "reasons": [], "limits": [],
                             "reviewed_hash": ""}
        rec = VisualReference(
            **{k: v for k, v in new.items()
               if k in VisualReference.__dataclass_fields__})
        rec.validate_or_raise()
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=json_replace(body,'$.status',"
                "'superseded') WHERE kind='visualreference' AND id=?"
                " AND revision=?", (ref_id, old["revision"]))
            u.records.put(rec)
            u.events.append(f"reference:{ref_id}", "replaced",
                            {"old_hash": old["artifact_sha256"],
                             "new_hash": art["sha256"],
                             "reviewer": reviewer})
        return rec

    def dependents(self, pack_id):
        """Downstream work bound to this pack's accepted hashes —
        generation requests referencing any accepted artifact, plus
        reviews targeting the pack hash. Reported stale, never moved."""
        pack = self._require_pack(pack_id)
        # any artifact ever bound to this pack's refs — accepted,
        # superseded or replaced — can be a dependency of downstream
        # work (all revisions, not just latest)
        bound, bound_ids = set(), set()
        for row in self.db.conn.execute(
                "SELECT body FROM records WHERE kind='visualreference'"
                ).fetchall():
            body = json.loads(row["body"])
            if body.get("pack_id") != pack_id:
                continue
            if body.get("artifact_sha256"):
                bound.add(body["artifact_sha256"])
            if body.get("artifact_id"):
                bound_ids.add(body["artifact_id"])
        stale = {"generation_requests": [], "reviews": []}
        for row in self.db.conn.execute(
                "SELECT id, body FROM records WHERE kind="
                "'generationrequest'").fetchall():
            body = json.loads(row["body"])
            ids = set(body.get("reference_artifact_ids") or [])
            sha = set()
            for aid in ids:
                art = self._artifact(aid)
                if art:
                    sha.add(art["sha256"])
            if (ids & bound_ids) or (sha & bound) or (ids & bound):
                stale["generation_requests"].append(row["id"])
        for row in self.db.conn.execute(
                "SELECT id, body FROM records WHERE kind='review'"
                ).fetchall():
            body = json.loads(row["body"])
            if body.get("target_hash") == pack.get("pack_hash"):
                stale["reviews"].append(row["id"])
        return stale

    def invalidate(self, pack_id, reason="reference_changed"):
        """Mark the pack stale and flag dependent reviews; the caller
        must issue an explicit plan revision — nothing silently mixes."""
        self._update_pack(pack_id, status="stale")
        deps = self.dependents(pack_id)
        with self.db.uow() as u:
            for rid in deps["reviews"]:
                row = u.records.get("review", rid)
                body = json.loads(row["body"])
                body["invalidated_by"] = reason
                u.conn.execute(
                    "UPDATE records SET body=? WHERE kind='review'"
                    " AND id=? AND revision=?",
                    (json.dumps(body), rid, row["revision"]))
            u.events.append(f"pack:{pack_id}", "invalidated",
                            {"reason": reason,
                             "stale_generation_requests":
                                 deps["generation_requests"],
                             "stale_reviews": deps["reviews"]})
        return deps

    # --------------------------------------------------------- helpers

    def _artifact(self, artifact_id):
        return self.db.uow().artifacts.get(artifact_id)

    def _get(self, kind, rid):
        row = self.db.uow().records.get(kind, rid)
        return json.loads(row["body"]) if row else None

    def _require_pack(self, pack_id):
        pack = self._get("referencepack", pack_id)
        if pack is None:
            raise ContractError("unknown_pack", "pack_id", pack_id)
        return pack

    def _update_pack(self, pack_id, **fields):
        row = self.db.uow().records.get("referencepack", pack_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='referencepack'"
                " AND id=? AND revision=?",
                (json.dumps(body), pack_id, row["revision"]))
