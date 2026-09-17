"""Experiment service (F14): frozen control + declared treatments.

- A (control) is built once from an accepted blueprint + template +
  product snapshots + original copy; it freezes products, presenter,
  voice, music, provider policy, template revision and total frames.
- B/C/D branch from A only: each declares hypothesis, primary metric,
  end-exclusive frame regions and allowed fields. Dependency changes
  (speech/captions/picture for copy edits) must live inside the same
  region — stale mouth motion is never reused.
- Acceptance is gated: accepted blueprint, resolvable template, clean
  one-variable check on every branch, claims grounded in product
  snapshot facts, supported effects.
- Post-freeze control edits create a new revision and mark variants +
  price assessments stale; they never rewrite the accepted row.
"""
import copy
import hashlib
import json

from ..domain.clocks import FrameInterval
from ..domain.errors import ContractError
from ..domain.records import (ExperimentRevision, ProviderPolicy,
                              VariantPlan)
from ..store.uow import utcnow
from ..templates.capabilities import capability_report
from .diff import check_treatment, diff_plans

FACTOR_REGION = {"hook": "first", "body": "middle", "ending": "last"}


def _hash_body(body):
    d = {k: v for k, v in body.items()
         if k not in ("content_hash", "created_at", "status", "revision")}
    return hashlib.sha256(json.dumps(
        d, sort_keys=True, default=str).encode()).hexdigest()


def load_experiment(row):
    d = json.loads(row["body"])
    if isinstance(d.get("provider_policy"), dict):
        d["provider_policy"] = ProviderPolicy(**d["provider_policy"])
    return ExperimentRevision(**d)


def load_variant(row):
    from .diff import to_interval
    d = json.loads(row["body"])
    d["allowed_regions"] = [to_interval(r)
                            for r in d.get("allowed_regions") or []]
    return VariantPlan(**d)


class ExperimentService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------- control

    def create(self, experiment_id, seed_id, blueprint, template,
               products, segments, voice=None, music=None,
               provider_policy=None, presenter="fictional_or_authorized"):
        """products: [ProductSnapshot]. segments: per-beat plan entries
        {id, slot_id, role, target, copy, speech, captions, picture,
        transition, claims}. Control A is implicit variant_key 'A'."""
        if blueprint.status != "accepted":
            raise ContractError("blueprint_not_accepted", "status",
                                blueprint.status)
        policy = provider_policy or ProviderPolicy()
        plan_body = {
            "segments": segments,
            "products": [{"snapshot_id": p.id, "revision": p.revision,
                          "product_id": p.product_id,
                          "variant_id": p.variant_id}
                         for p in products],
            "voice": voice or {"id": "new_selected", "model": "",
                               "settings": {}},
            "music": music or {"role": "bed"},
            "presenter": presenter,
            "provider_policy": policy.to_dict() if hasattr(
                policy, "to_dict") else dict(policy.__dict__),
            "template_ref": {"id": template.id,
                             "revision": template.revision},
            "target_frames": blueprint.target_frames,
        }
        rev = ExperimentRevision(
            schema_version="experiment.v1", id=f"exp:{experiment_id}",
            created_at=utcnow(), experiment_id=experiment_id,
            revision=1, status="draft", seed_id=seed_id,
            blueprint_hash=blueprint.content_hash,
            template_ref=f"{template.id}@{template.revision}",
            product_snapshot_ids=[p.id for p in products],
            presenter_ref=presenter,
            voice=plan_body["voice"],
            provider_policy=policy,
            segments=segments,
            music=plan_body["music"],
            output_clock={"num": blueprint.clock.num,
                          "den": blueprint.clock.den},
            packaging=plan_body)
        rev.content_hash = _hash_body({**rev.to_dict(),
                                       "packaging": plan_body})
        a = VariantPlan(
            schema_version="variant_plan.v1",
            id=f"{experiment_id}:a", created_at=utcnow(),
            experiment_id=experiment_id, experiment_revision=1,
            variant_key="A", target_frames=blueprint.target_frames,
            segments=copy.deepcopy(segments), status="draft",
            primary_metric="retention")
        a.content_hash = _hash_body(a.to_dict())
        rev.validate_or_raise()
        a.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(rev)
            u.records.put(a)
            u.events.append(f"experiment:{experiment_id}", "created",
                            {"control": "A",
                             "products": [p.id for p in products]})
        return {"control": rev, "variant_a": a}

    # ------------------------------------------------------ branches

    def branch(self, experiment_id, variant_key, factor, regions,
               apply_edits, hypothesis, primary_metric,
               allowed_fields, dependent_fields=()):
        """Branch B/C/D from the frozen control. `regions` are
        end-exclusive frame intervals; `apply_edits(plan_body)` mutates
        a copy and returns it."""
        control = self._latest(experiment_id)
        base = copy.deepcopy(control.packaging)
        body = apply_edits(base) or base
        from .diff import to_interval
        regions_iv = [to_interval(r) for r in regions]
        problems = check_treatment(
            control.packaging, body, regions_iv, allowed_fields,
            locked_fields=list(control.packaging.keys()))
        if problems:
            raise ContractError("treatment_violation", "branch",
                                json.dumps(problems)[:2000])
        row = self.db.uow().records.get(
            "experimentrevision", f"exp:{experiment_id}")
        v = VariantPlan(
            schema_version="variant_plan.v1",
            id=f"{experiment_id}:{variant_key.lower()}", created_at=utcnow(),
            experiment_id=experiment_id,
            experiment_revision=row["revision"],
            revision=row["revision"],
            variant_key=variant_key, hypothesis=hypothesis,
            changed_factor=factor, allowed_regions=regions_iv,
            allowed_fields=list(allowed_fields),
            locked_fields=list(control.packaging.keys()),
            target_frames=control.packaging["target_frames"],
            primary_metric=primary_metric,
            segments=body["segments"],
            dependent_fields=list(dependent_fields),
            status="draft")
        v.content_hash = _hash_body(v.to_dict())
        v.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(v)
            u.events.append(f"experiment:{experiment_id}",
                            "branched",
                            {"variant": variant_key, "factor": factor})
        return v

    # -------------------------------------------------------- review

    def review(self, experiment_id, variant_key):
        control = self._latest(experiment_id)
        v = self._variant(experiment_id, variant_key)
        body = {**control.packaging, "segments": v.segments}
        return {"diff": diff_plans(control.packaging["segments"],
                                   v.segments),
                "problems": check_treatment(
                    control.packaging, body, v.allowed_regions,
                    v.allowed_fields, v.locked_fields),
                "unique_work_segments": len(v.segments)}

    # ------------------------------------------------------ acceptance

    def acceptance_report(self, experiment_id, blueprint, template,
                          snapshots):
        """What acceptance will check — incomplete analysis or
        unsupported requirements block before freeze."""
        control = self._latest(experiment_id)
        problems = []
        if blueprint.status != "accepted":
            problems.append({"flag": "analysis_incomplete",
                             "detail": "blueprint not accepted"})
        claim_texts = {c["text"] for p in snapshots
                       for c in p.claims}
        # Every variant's claims face the pinned product evidence — a
        # treatment may not introduce support the control never had.
        segments = list(control.packaging["segments"])
        for key in "BCD":
            row = self.db.uow().records.get(
                "variantplan", f"{experiment_id}:{key.lower()}")
            if row:
                segments += (json.loads(row["body"]).get("segments")
                             or [])
        for seg in segments:
            for claim in seg.get("claims") or []:
                if claim not in claim_texts:
                    problems.append({"flag": "unsupported_claim",
                                     "detail": claim[:60]})
        from ..domain.records import Slot
        slots = [Slot(id=s["id"], effects=s.get("effects") or [],
                      transition_out=s.get("transition", "cut"))
                 for s in control.packaging["segments"]]
        cap = capability_report(slots)
        if cap["unsupported"]:
            problems.append({"flag": "unsupported_shot",
                             "detail": json.dumps(cap["unsupported"])})
        return {"problems": problems, "hash": control.content_hash}

    def accept(self, experiment_id, expected_hash):
        control = self._latest(experiment_id)
        if control.content_hash != expected_hash:
            raise ContractError("revision_mismatch", "content_hash")
        if control.status == "accepted":
            return control
        self._set_status("experimentrevision", control.id, "accepted")
        for k in "abcd":
            row = self.db.uow().records.get(
                "variantplan", f"{experiment_id}:{k}")
            if row and json.loads(row["body"]).get("status") == "draft":
                self._set_status("variantplan",
                                 f"{experiment_id}:{k}", "accepted")
        with self.db.uow() as u:
            u.events.append(f"experiment:{experiment_id}", "accepted",
                            {"hash": expected_hash})
        return self._latest(experiment_id)

    # ---------------------------------------------------- post-freeze

    def revise_control(self, experiment_id, mutate, reason):
        """Post-freeze edit: new revision; variants + prices go stale.
        The accepted row is never rewritten."""
        control = self._latest(experiment_id)
        body = json.loads(self.db.uow().records.get(
            "experimentrevision", control.id)["body"])
        body = mutate(dict(body)) or body
        body["revision"] = control.revision + 1
        body["status"] = "draft"
        body["parent_revision"] = control.revision
        body["parent_hash"] = control.content_hash
        body["content_hash"] = _hash_body(body)
        child = load_experiment({"body": json.dumps(body)})
        staled = []
        with self.db.uow() as u:
            u.records.put(child)
            for row in u.conn.execute(
                    "SELECT id, revision, body FROM records WHERE "
                    "kind='variantplan' AND id LIKE ?",
                    (f"{experiment_id}:%",)).fetchall():
                vb = json.loads(row["body"])
                if vb.get("stale_reason"):
                    continue
                # Preserve the old variant. Staleness is a relation to the
                # current experiment revision, not a rewrite of history.
                staled.append(row["id"])
            a = self._variant(experiment_id, "A")
            a.revision = child.revision
            a.experiment_revision = child.revision
            a.segments = copy.deepcopy(child.packaging["segments"])
            a.status = "draft"
            a.stale_reason = ""
            a.content_hash = _hash_body(a.to_dict())
            u.records.put(a)
            u.conn.execute(
                "UPDATE records SET body=json_set(body,'$.status',"
                "'stale') WHERE kind='priceassessment' AND "
                "json_extract(body,'$.plan_hash')=?",
                (control.content_hash,))
            u.events.append(f"experiment:{experiment_id}", "revised",
                            {"revision": body["revision"],
                             "reason": reason, "staled": staled})
        return {"revision": child, "staled": staled}

    # ------------------------------------------------------- helpers

    def _latest(self, experiment_id):
        row = self.db.uow().records.get(
            "experimentrevision", f"exp:{experiment_id}")
        if row is None:
            raise ContractError("unknown_experiment", "id",
                                experiment_id)
        return load_experiment(row)

    def _variant(self, experiment_id, key):
        row = self.db.uow().records.get(
            "variantplan", f"{experiment_id}:{key.lower()}")
        if row is None:
            raise ContractError("unknown_variant", "key", key)
        variant = load_variant(row)
        if variant.experiment_revision != self._latest(experiment_id).revision:
            variant.stale_reason = "control_revised"
        return variant

    def _set_status(self, kind, rid, status):
        row = self.db.uow().records.get(kind, rid)
        body = json.loads(row["body"])
        body["status"] = status
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind=? AND id=? AND "
                "revision=?", (json.dumps(body), kind, rid,
                               row["revision"]))
