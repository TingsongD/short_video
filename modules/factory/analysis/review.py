"""Blueprint timeline review (F12 checklist 5–6).

- flags() names what's wrong; nothing auto-passes.
- accept() is gated on the exact content hash the reviewer saw — a
  stale hash is a typed mismatch, not a silent acceptance of drift.
- edit() produces a child revision with parent_hash; dependents
  (templates bound to the old hash) are listed, never silently moved.
"""
import json

from ..domain.clocks import check_partition
from ..domain.errors import ContractError
from .service import load_blueprint


class BlueprintReview:
    def __init__(self, db):
        self.db = db

    def flags(self, blueprint_id):
        bp = self._load(blueprint_id)
        flags = []
        for e in check_partition([b.target for b in bp.beats],
                                 bp.target_frames):
            flags.append({"flag": e.code, "detail": e.detail})
        if bp.audio.get("present") and not bp.speech.get("transcript"):
            flags.append({"flag": "untranscribed_speech",
                          "detail": "audio present, transcript empty"})
        if not bp.audio.get("present"):
            flags.append({"flag": "audio_missing",
                          "detail": "no audio stream; speech/music "
                                    "facts stay unknown"})
        for b in bp.beats:
            if b.confidence != "reviewed":
                flags.append({"flag": "low_confidence_scene",
                              "detail": f"beat {b.id}: {b.confidence}"})
            if b.role == "product_reveal" and len(b.evidence_ids) < 1:
                flags.append({"flag": "unclear_product_action",
                              "detail": f"beat {b.id}: no evidence"})
            if b.role in ("product_reveal", "proof") and \
                    not b.speech_segment_id:
                flags.append({"flag": "unclear_product_action",
                              "detail": f"beat {b.id}: no speech link"})
        return flags

    def accept(self, blueprint_id, expected_hash, reviewer="",
               allow_flags=False, notes=""):
        bp = self._load(blueprint_id)
        if bp.content_hash != expected_hash:
            raise ContractError("revision_mismatch", "content_hash",
                                "blueprint changed since review")
        flags = self.flags(blueprint_id)
        if flags and not allow_flags:
            raise ContractError("unresolved_flags", "flags",
                                "review flags must be resolved first")
        if flags and (not str(reviewer or "").strip() or
                      str(reviewer).strip() == "auto-pipeline"):
            raise ContractError("human_review_required", "reviewer",
                                "flag overrides require an explicit human "
                                "reviewer")
        from .deep import analysis_gate
        analysis = analysis_gate(self.db, bp.seed_id,
                                 (bp.provenance or {})
                                 .get("artifact_sha256", ""))
        self._update(blueprint_id, status="accepted",
                     analysis={"id": analysis.id,
                               "revision": analysis.revision})
        self._event(blueprint_id, "accepted",
                    {"hash": expected_hash, "reviewer": reviewer,
                     "analysis": analysis.id,
                     "analysis_revision": analysis.revision,
                     "flags_overridden": flags if allow_flags else [],
                     "notes": str(notes or "")})
        return self._load(blueprint_id)

    def reject(self, blueprint_id, reason):
        if not reason:
            raise ContractError("reject_needs_reason", "reason")
        self._update(blueprint_id, status="rejected")
        self._event(blueprint_id, "rejected", {"reason": reason})

    def edit(self, blueprint_id, mutate, reason):
        """mutate(bp_dict) → bp_dict. Produces a child draft revision;
        the old row is marked superseded and dependents are returned
        so callers can decide what to rebuild — nothing auto-migrates."""
        bp = self._load(blueprint_id)
        body = json.loads(self.db.uow().records.get(
            "referenceblueprint", blueprint_id)["body"])
        new_body = mutate(dict(body)) or body
        new_body["revision"] = bp.revision + 1
        new_body["status"] = "draft"
        new_body["parent_hash"] = bp.content_hash
        from .service import AnalysisService
        child = load_blueprint({"body": json.dumps(new_body)})
        child.content_hash = AnalysisService._hash(child)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=json_replace(body,'$.status',"
                "'superseded') WHERE kind='referenceblueprint' AND id=? "
                "AND revision=?", (blueprint_id, bp.revision))
            u.records.put(child)
            u.events.append(f"blueprint:{blueprint_id}", "edited",
                            {"revision": child.revision,
                             "parent_hash": bp.content_hash,
                             "reason": reason})
        return {"blueprint": child,
                "stale_dependents": self.dependents_of(bp.content_hash)}

    def dependents_of(self, content_hash):
        """Templates/plans bound to this blueprint hash — now stale."""
        stale = []
        for row in self.db.conn.execute(
                "SELECT id, body FROM records WHERE kind IN "
                "('formattemplate','experimentrevision')").fetchall():
            body = json.loads(row["body"])
            if body.get("derived_from_blueprint") == content_hash or \
                    body.get("blueprint_hash") == content_hash:
                stale.append(row["id"])
        return stale

    # --------------------------------------------------------- helpers

    def _load(self, blueprint_id):
        row = self.db.uow().records.get("referenceblueprint",
                                        blueprint_id)
        if row is None:
            raise ContractError("unknown_blueprint", "id", blueprint_id)
        return load_blueprint(row)

    def _update(self, blueprint_id, **fields):
        row = self.db.uow().records.get("referenceblueprint",
                                        blueprint_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='referenceblueprint'"
                " AND id=? AND revision=?",
                (json.dumps(body), blueprint_id, row["revision"]))

    def _event(self, blueprint_id, kind, body):
        with self.db.uow() as u:
            u.events.append(f"blueprint:{blueprint_id}", kind, body)
