"""PL-02 metadata production: platform-specific candidate packages
grounded in accepted creative evidence, validated, selected and frozen
before publication planning. Deterministic generation is the offline
default; provider-assisted generation is an optional injected route.
"""
import json
import uuid
from datetime import datetime, timezone

from ..domain.errors import ContractError
from ..domain.records import (MetadataPackage, PUBLISH_PLATFORMS,
                              content_hash)


def _now():
    return datetime.now(timezone.utc).isoformat()


# Platform field contracts (handover §6). Limits are conservative and
# must be re-verified against the selected provider's live contract
# during qualification — they are guards, not optimization advice.
PLATFORM_FIELDS = {
    "youtube": {"fields": {"title": 100, "description": 5000,
                           "tags": 500},
                "required": ["title"],
                "hashtags_in": "description"},
    "tiktok": {"fields": {"caption": 2200},
               "required": ["caption"],
               "hashtags_in": "caption"},
    "instagram": {"fields": {"caption": 2200},
                  "required": ["caption"],
                  "hashtags_in": "caption"},
    "facebook": {"fields": {"title": 255, "description": 63206},
                 "required": ["description"],
                 "hashtags_in": "description"},
}

DISCLOSURE_FIELDS = ("ai_content", "branded_content", "audience")


class MetadataService:
    def __init__(self, db):
        self.db = db

    # -------------------------------------------------- generation --

    def draft(self, variant_plan_id, platform, *, context=None, now=""):
        """Deterministic candidates from declared creative context —
        an honest starting point, never a claimed optimum."""
        now = now or _now()
        if platform not in PUBLISH_PLATFORMS:
            raise ContractError("unsupported_platform", "platform",
                                platform)
        spec = PLATFORM_FIELDS[platform]
        ctx = dict(context or {})
        seed_title = (ctx.get("seed_title") or "").strip()
        treatment = (ctx.get("treatment") or "").strip()
        hypothesis = (ctx.get("hypothesis") or "").strip()
        base = seed_title or "Untitled"
        cands = []
        titles = [base,
                  f"{base} — wait for it",
                  f"{base} (the ending)"]
        for i, t in enumerate(titles):
            fields = {}
            for fname in spec["fields"]:
                if fname == "title":
                    fields["title"] = t[:spec["fields"]["title"]]
                elif fname == "description":
                    desc = base
                    if treatment:
                        desc = f"{base}\n\n{treatment[:400]}"
                    fields["description"] = desc[:spec["fields"]["description"]]
                elif fname == "caption":
                    cap = base if not hypothesis else f"{base} — {hypothesis}"
                    fields["caption"] = cap[:spec["fields"]["caption"]]
                elif fname == "tags":
                    fields["tags"] = ""
            cands.append({"id": f"c{i+1}", "via": "deterministic",
                          "fields": fields,
                          "notes": "draft from accepted evidence — "
                                   "edit before freezing"})
        return cands

    def create(self, variant_plan_id, platform, *, final_sha256="",
               candidates=None, generator=None, context=None,
               disclosures=None, now=""):
        """Create a draft MetadataPackage for (variant, platform)."""
        now = now or _now()
        cands = list(candidates or self.draft(
            variant_plan_id, platform, context=context, now=now))
        if not cands:
            raise ContractError("no_metadata_candidates", "candidates")
        pkg = MetadataPackage(
            schema_version="metadatapackage.v1",
            id=f"mp-{uuid.uuid4().hex[:12]}", created_at=now,
            variant_plan_id=variant_plan_id, platform=platform,
            final_sha256=final_sha256, revision=0, status="draft",
            candidates=cands,
            disclosures=dict(disclosures or {}),
            generator=dict(generator or {"route": "deterministic"}))
        pkg.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(pkg)
        return pkg

    # -------------------------------------------------- validation --

    def check(self, fields, platform, disclosures=None):
        """(ok, errors[]) — field limits, required fields, disclosure
        completeness. Unknown fields are named, not silently dropped."""
        spec = PLATFORM_FIELDS.get(platform)
        if not spec:
            return False, [{"field": "platform",
                            "error": "unsupported_platform"}]
        errors = []
        for name in spec["required"]:
            if not (fields.get(name) or "").strip():
                errors.append({"field": name, "error": "required"})
        for name, value in fields.items():
            if name == "hashtags":
                continue
            limit = spec["fields"].get(name)
            if limit is None:
                errors.append({"field": name,
                               "error": "unsupported_field"})
            elif len(str(value)) > limit:
                errors.append({"field": name,
                               "error": f"exceeds_{limit}"})
        disc = dict(disclosures or {})
        for d in DISCLOSURE_FIELDS:
            if d not in disc:
                errors.append({"field": d,
                               "error": "disclosure_unanswered"})
        return not errors, errors

    # ---------------------------------------------------- selection --

    def _get(self, package_id):
        row = self.db.uow().records.get("metadatapackage", package_id)
        if not row:
            raise ContractError("not_found", "metadata_package",
                                package_id)
        return json.loads(row["body"]), row["version"]

    def select(self, package_id, *, candidate_id="", fields=None,
               revision=None, reviewer="", now=""):
        """Choose a candidate (or explicit edited fields) and validate.
        `revision` is the row version the caller last saw (CAS handle)."""
        now = now or _now()
        body, ver = self._get(package_id)
        if revision is not None and revision != ver:
            raise ContractError("stale_revision", "metadata_package")
        if body["status"] == "frozen":
            raise ContractError("package_frozen", package_id)
        if fields is None:
            cand = next((c for c in body["candidates"]
                         if c["id"] == candidate_id), None)
            if not cand:
                raise ContractError("unknown_candidate", candidate_id)
            fields = dict(cand["fields"])
        ok, errors = self.check(fields, body["platform"],
                                body.get("disclosures"))
        body["selected"] = fields
        body["validation"] = {"ok": ok, "errors": errors,
                              "checked_fields": sorted(fields),
                              "reviewer": reviewer, "checked_at": now}
        with self.db.uow() as u:
            u.records.put(MetadataPackage(
                **{k: v for k, v in body.items()
                   if k in MetadataPackage.__dataclass_fields__}),
                expected_version=ver)
        return body

    def freeze(self, package_id, *, revision=None, now=""):
        """Freeze the validated selection. A frozen package is the only
        form publication planning may bind (PL-T06)."""
        now = now or _now()
        body, ver = self._get(package_id)
        if revision is not None and revision != ver:
            raise ContractError("stale_revision", "metadata_package")
        if not body.get("selected"):
            raise ContractError("no_selection", package_id)
        if not body.get("validation", {}).get("ok"):
            raise ContractError("validation_failed", package_id,
                                body.get("validation", {}).get("errors"))
        body["status"] = "frozen"
        body["content_hash"] = content_hash(
            {"variant_plan_id": body["variant_plan_id"],
             "platform": body["platform"],
             "final_sha256": body["final_sha256"],
             "selected": body["selected"],
             "disclosures": body["disclosures"]})
        with self.db.uow() as u:
            u.records.put(MetadataPackage(
                **{k: v for k, v in body.items()
                   if k in MetadataPackage.__dataclass_fields__}),
                expected_version=ver)
        return body
