"""M6 manifest: turn the assets folder into asset_manifest.json.
Every shot must be covered by a validated file; uncovered shots are listed in
`missing_shots` (schema allows the extra top-level field) and `complete`
is false. Stock substitution is an explicit operator choice."""
import json
from pathlib import Path

from modules.common.schema import validate

from .intake import scan_folder


def build_manifest(video_id, assets_dir, shot_count, shot_kinds=None, shot_durations=None):
    """shot_kinds: optional {idx: 'video'|'image'} from the shot list."""
    found = scan_folder(assets_dir, shot_kinds, shot_durations)
    shot_kinds = shot_kinds or {}
    assets, missing = [], []
    for idx in range(shot_count):
        e = found.get(idx)
        if not e or not e["ok"]:
            missing.append(idx)
            continue
        entry = {
            "shot_idx": idx,
            "file": e["file"],
            "kind": e["kind"],
            "source": e["source"],
        }
        info = e.get("detail") if isinstance(e.get("detail"), dict) else None
        if info:
            if info.get("duration_s") is not None and entry["kind"] == "video":
                entry["duration_s"] = round(info["duration_s"], 2)
            entry["width"], entry["height"] = info["width"], info["height"]
        assets.append(entry)
    doc = {
        "video_id": video_id,
        "assets": sorted(assets, key=lambda a: a["shot_idx"]),
        "missing_shots": missing,
        "complete": not missing,
        "rejected_shots": {str(idx): found[idx]["detail"] for idx in missing if idx in found},
    }
    # The frozen contract requires at least one asset. Empty results are a local
    # intake status, never a contract file passed to another module.
    return validate(doc, "asset_manifest.schema.json") if assets else doc


def write_manifest(doc, assets_dir):
    p = Path(assets_dir) / "manifest.json"
    if not doc["assets"]:
        p.unlink(missing_ok=True)  # invalidate an older, now stale manifest
        return None
    validate(doc, "asset_manifest.schema.json")
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p
