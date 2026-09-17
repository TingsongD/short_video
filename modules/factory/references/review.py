"""Reference review (F18 checklist 5): acceptance pinned to the exact
artifact hash the reviewer saw; rejected references cannot feed paid
picture jobs; replacements are new attempts within repair authority.
"""
import json

from ..domain.errors import ContractError
from .pack import ReferencePackService
from .validate import validate_reference


class ReferenceReview:
    def __init__(self, db, packs: ReferencePackService,
                 max_repairs=2):
        self.db = db
        self.packs = packs
        self.max_repairs = max_repairs

    def flags(self, ref_id, snapshot_facts=None):
        ref = self._get(ref_id)
        out = validate_reference(ref, snapshot_facts or {})
        if ref["role"].startswith("product") and snapshot_facts \
                and ref.get("variant_id") and \
                ref["variant_id"] != snapshot_facts.get("variant_id"):
            out["flags"].append({"flag": "variant_mismatch", "detail":
                                 f"ref variant {ref['variant_id']} vs "
                                 f"{snapshot_facts.get('variant_id')}"})
        return out["flags"]

    def accept(self, ref_id, artifact_hash, reviewer,
               limits=None, snapshot_facts=None):
        if not reviewer:
            raise ContractError("missing_field", "reviewer")
        ref = self._get(ref_id)
        if ref["artifact_sha256"] != artifact_hash:
            raise ContractError("revision_mismatch", "artifact_sha256",
                                "reference changed since review")
        flags = self.flags(ref_id, snapshot_facts)
        if flags:
            raise ContractError("unresolved_flags", "flags",
                                json.dumps([f["flag"] for f in flags]))
        self._set(ref_id, status="accepted", acceptance={
            "state": "accepted", "reviewer": reviewer,
            "reasons": [], "limits": list(limits or []),
            "reviewed_hash": artifact_hash})
        self.packs.refresh_pack_hash(ref["pack_id"])
        return self._get(ref_id)

    def reject(self, ref_id, reviewer, reasons):
        if not reasons:
            raise ContractError("reject_needs_reason", "reasons")
        ref = self._get(ref_id)
        self._set(ref_id, status="rejected", acceptance={
            "state": "rejected", "reviewer": reviewer,
            "reasons": list(reasons), "limits": [],
            "reviewed_hash": ref["artifact_sha256"]})
        self.packs.refresh_pack_hash(ref["pack_id"])

    def replace(self, ref_id, new_artifact_id, reviewer):
        """Repair attempt — bounded by max_repairs; prior attempts and
        their cost remain on record."""
        ref = self._get(ref_id)
        pack = self.packs._require_pack(ref["pack_id"])
        if pack["repair_attempts"] >= self.max_repairs:
            raise ContractError("repair_limit_reached", "repair_attempts",
                                self.max_repairs)
        self.packs._update_pack(ref["pack_id"],
                                repair_attempts=pack["repair_attempts"] + 1)
        return self.packs.replace(ref_id, new_artifact_id, reviewer)

    def usable_hashes(self, pack_id):
        """Hashes a paid picture job may consume — accepted only."""
        return set(self.packs.selection(pack_id).values())

    def gate_request(self, pack_id, artifact_shas):
        """Dispatch guard: every referenced hash must be accepted."""
        usable = self.usable_hashes(pack_id)
        rejected = [h for h in artifact_shas if h not in usable]
        if rejected:
            raise ContractError("reference_not_accepted",
                                "reference_artifacts", rejected)
        return True

    # --------------------------------------------------------- helpers

    def _get(self, ref_id):
        ref = self.packs.get(ref_id)
        if ref is None:
            raise ContractError("unknown_reference", "id", ref_id)
        return ref

    def _set(self, ref_id, **fields):
        row = self.db.uow().records.get("visualreference", ref_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='visualreference'"
                " AND id=? AND revision=?",
                (json.dumps(body), ref_id, row["revision"]))
            u.events.append(f"reference:{ref_id}",
                            fields.get("status", "updated"),
                            {"reviewer": (fields.get("acceptance") or {})
                             .get("reviewer", "")})
