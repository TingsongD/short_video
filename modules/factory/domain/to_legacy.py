"""Factory → frozen legacy contract conversion (handover §7.5, F02-M04).

Converts factory records into legacy schema payloads when a faithful
mapping exists. Refuses loudly when it doesn't — a Vertex artifact can
never be relabeled jimeng/manual/stock to fit the frozen enum, and a
20-take plan never squeezes into the legacy 4–7-shot pipeline.
"""
from .errors_compat import jsonschema_validate
from .errors import ContractError
from .legacy import CompatibilityReport, INCOMPATIBLE

# Frozen legacy enums (schemas/asset_manifest.schema.json)
LEGACY_SOURCES = {"jimeng", "manual", "stock"}
LEGACY_KINDS = {"video", "image"}
LEGACY_MIN_SHOTS, LEGACY_MAX_SHOTS = 4, 7

_PROV_TO_LEGACY = {
    "jimeng_canvas": "jimeng",
    "manual": "manual",
    "stock": "stock",
    # google_vertex / generated_other / elevenlabs / seed_source /
    # shopify have no faithful legacy label — refuse, never mislabel.
}


def to_legacy_asset_manifest(video_id, asset_uses, artifacts_by_id):
    """Build a legacy AssetManifest payload or return a refusal report.

    `asset_uses`: ordered AssetUse records. `artifacts_by_id`: id ->
    Artifact. Returns (payload, report); payload is None on refusal.
    """
    r = CompatibilityReport("legacy_asset_manifest")
    payload = {"video_id": video_id, "assets": []}
    reasons = []
    n = len(asset_uses)
    if n < LEGACY_MIN_SHOTS or n > LEGACY_MAX_SHOTS:
        reasons.append(f"shot_count {n} outside legacy {LEGACY_MIN_SHOTS}-"
                       f"{LEGACY_MAX_SHOTS}")
        r.incompatible("shot_count", reasons[-1])
    else:
        r.mapped("shot_count", n)
    for i, use in enumerate(asset_uses):
        art = artifacts_by_id.get(use.artifact_id)
        if art is None:
            r.incompatible(f"assets[{i}].file", "unknown artifact")
            reasons.append(f"assets[{i}] missing artifact")
            continue
        bad = False
        if art.kind not in LEGACY_KINDS:
            r.incompatible(f"assets[{i}].kind",
                           f"kind '{art.kind}' not in legacy enum")
            reasons.append(f"assets[{i}] kind '{art.kind}' not in legacy enum")
            bad = True
        src = _PROV_TO_LEGACY.get(art.provenance)
        if src is None:
            r.incompatible(
                f"assets[{i}].source",
                f"provenance '{art.provenance}' has no faithful legacy "
                "source label (refusing to mislabel)")
            reasons.append(
                f"assets[{i}] provenance '{art.provenance}' has no faithful "
                "legacy source label (refusing to mislabel)")
            bad = True
        else:
            r.mapped(f"assets[{i}].source", src)
        if bad:
            continue
        asset = {"shot_idx": i, "file": art.local_path or art.id,
                 "kind": art.kind, "source": src,
                 "duration_s": (use.source.length / 30.0 if use.source
                                else 1.0)}
        if art.native_width:
            asset["width"] = art.native_width
        if art.native_height:
            asset["height"] = art.native_height
        payload["assets"].append(asset)
    if reasons:
        return None, r
    r.mapped("video_id", video_id)
    return payload, r


def validate_against_frozen(payload, schema_path):
    """Validate a produced payload against a frozen legacy schema file."""
    return jsonschema_validate(payload, schema_path)


def convert_or_refuse(video_id, asset_uses, artifacts_by_id, schema_path):
    """Full path: convert then validate. Raises ContractError on refusal
    (callers get the report attached) so invalid data never crosses."""
    payload, report = to_legacy_asset_manifest(video_id, asset_uses,
                                               artifacts_by_id)
    if payload is None:
        notes = [f"{k}: {n}" for k, (s, v, n) in report.fields.items()
                 if s == INCOMPATIBLE]
        err = ContractError("legacy_conversion_refused", "assets",
                            "; ".join(notes))
        err.report = report.to_dict()
        raise err
    problems = validate_against_frozen(payload, schema_path)
    if problems:
        err = ContractError("legacy_schema_reject", "payload",
                            "; ".join(problems))
        err.report = report.to_dict()
        raise err
    return payload, report
