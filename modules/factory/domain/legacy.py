"""Legacy project → factory compatibility conversion (handover §7.5).

Produces a CompatibilityReport per field: mapped / unresolved /
incompatible. Unsupported mappings refuse loudly; missing values become
null, never zero; a Vertex generation can never be recorded as Jimeng.
"""
from .errors import ContractError


MAPPED = "mapped"
UNRESOLVED = "unresolved"
INCOMPATIBLE = "incompatible"


class CompatibilityReport:
    def __init__(self, source_kind):
        self.source_kind = source_kind
        self.fields = {}             # field -> (status, value, note)

    def mapped(self, field, value, note=""):
        self.fields[field] = (MAPPED, value, note)

    def unresolved(self, field, note):
        self.fields[field] = (UNRESOLVED, None, note)

    def incompatible(self, field, note):
        self.fields[field] = (INCOMPATIBLE, None, note)

    def status_counts(self):
        counts = {MAPPED: 0, UNRESOLVED: 0, INCOMPATIBLE: 0}
        for status, _, _ in self.fields.values():
            counts[status] += 1
        return counts

    def to_dict(self):
        return {"source_kind": self.source_kind,
                "fields": {k: {"status": s, "value": v, "note": n}
                           for k, (s, v, n) in self.fields.items()},
                "counts": self.status_counts()}


_PROV_MAP = {
    "canvas": "jimeng_canvas",
    "jimeng": "jimeng_canvas",
    "jimeng_canvas": "jimeng_canvas",
    "vertex": "google_vertex",
    "google_vertex": "google_vertex",
    "veo": "google_vertex",
    "pexels": "stock",
    "elevenlabs": "elevenlabs",
    "manual": "manual",
}


def map_provenance(legacy_provenance):
    """Translate a legacy source label. Unknown labels refuse loudly —
    provenance is never guessed (§7.5)."""
    if legacy_provenance is None:
        raise ContractError("missing_provenance", "provenance")
    key = str(legacy_provenance).strip().lower()
    if key not in _PROV_MAP:
        raise ContractError("unsupported_provenance", "provenance",
                            legacy_provenance)
    return _PROV_MAP[key]


def convert_produced_video(legacy):
    """Map a legacy production record (PROGRESS row / project dict) to
    factory fields. Returns CompatibilityReport."""
    r = CompatibilityReport("produced_video")
    if legacy.get("id"):
        r.mapped("legacy_id", legacy["id"])
    else:
        r.incompatible("legacy_id", "no stable identity")
    for src, dst in (("hook", "hook_text"), ("format", "format_id"),
                     ("niche", "niche_id"), ("title", "title"),
                     ("drive_link", "drive_link")):
        if legacy.get(src):
            r.mapped(dst, legacy[src])
        else:
            r.unresolved(dst, f"legacy field '{src}' absent")
    if legacy.get("renderer"):
        r.mapped("renderer", legacy["renderer"])
    else:
        r.unresolved("renderer", "historical rows predate renderer records")
    # provenance requires explicit evidence — never inferred
    prov = legacy.get("provenance") or legacy.get("provider")
    try:
        r.mapped("provenance", map_provenance(prov))
    except ContractError as exc:
        r.unresolved("provenance", exc.detail or exc.code)
    # durable factory linkage does not exist for historical rows
    r.unresolved("experiment_revision",
                 "legacy rows predate experiment revisions")
    r.unresolved("artifact_hash", "no recorded content hash in legacy data")
    r.unresolved("review", "no per-artifact review records in legacy data")
    return r
