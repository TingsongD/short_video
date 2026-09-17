"""`inspect` views over workspace state (runbook §3).

A view reports real workspace data. Where the owning module is not built,
it returns an explicit unavailable status instead of a fabricated table.
"""
import json
from pathlib import Path

from .registry import MODULES, IMPLEMENTED

VIEW_MODULE = {
    "contracts": "F02", "assets": "F04", "seeds": "F09", "products": "F11",
    "blueprints": "F12", "experiments": "F14", "jobs": "F06",
    "events": "F08", "budgets": "F05", "provider-calls": "F01",
    "reviews": "F24", "deliveries": "F25", "publications": "F31",
    "metrics": "F32", "resources": "F26", "health": "F30",
    "decisions": "F33", "drills": "F34", "release": "F35",
}


def provider_calls(workspace):
    out = {}
    fr = workspace.path / "fake_remote"
    for f in sorted(fr.glob("*.json")):
        if f.name == "ids.json":
            continue
        doc = json.loads(f.read_text())
        out[f.stem] = {"counters": doc.get("counters", {}),
                       "operations": {k: {kk: v for kk, v in op.items()
                                          if kk in ("status", "seq", "polls",
                                                    "request_hash")}
                                      for k, op in
                                      doc.get("operations", {}).items()},
                       "uploads": len(doc.get("uploads", {})),
                       "publications": len(doc.get("publications", {}))}
    return out


def runs_view(workspace):
    out = []
    runs = workspace.path / "runs"
    for f in sorted(runs.glob("*/*/run.json")):
        doc = json.loads(f.read_text())
        out.append({"case": doc.get("case_id"), "run": doc.get("run_id"),
                    "status": doc.get("status")})
    return out


def health(workspace):
    meta = workspace.meta
    lock = workspace.path / "fixture-lock.json"
    return {"workspace": str(workspace.path), "fixture": meta.get("fixture"),
            "created_at": meta.get("created_at"),
            "fixture_files": len(json.loads(lock.read_text())["files"])
            if lock.exists() else 0,
            "implemented_modules": sorted(IMPLEMENTED),
            "registered_modules": len(MODULES)}


def inspect(workspace, view):
    if view not in VIEW_MODULE:
        raise KeyError(f"unknown inspect view {view!r}; supported: "
                       + ", ".join(sorted(VIEW_MODULE)))
    if view == "provider-calls":
        return {"view": view, "status": "ok", "data": provider_calls(workspace)}
    if view == "events":
        return {"view": view, "status": "ok", "data": runs_view(workspace)}
    if view == "health":
        return {"view": view, "status": "ok", "data": health(workspace)}
    owner = VIEW_MODULE[view]
    if owner not in IMPLEMENTED:
        return {"view": view, "status": "unavailable",
                "reason": f"owning module {owner} not implemented"}
    # Implemented modules register a data reader in their workspace db dir.
    source = workspace.path / "db" / f"{view}.json"
    if not source.exists():
        return {"view": view, "status": "ok", "data": []}
    return {"view": view, "status": "ok",
            "data": json.loads(source.read_text())}
