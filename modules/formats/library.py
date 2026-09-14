"""M3: CRUD over data/formats/library.json (format_library contract).
Writes are schema-validated; format_ids are stable slugs."""
import json
import re
from pathlib import Path

from modules.common.schema import validate

STATUSES = ("candidate", "proven", "retired")


def load(path):
    p = Path(path)
    if not p.exists():
        return {"version": 1, "formats": []}
    return json.loads(p.read_text())


def save(lib, path):
    validate(lib, "format_library.schema.json")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(lib, indent=2) + "\n", encoding="utf-8")


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "format"


def new_id(lib, name):
    base = f"fmt-{_slug(name)}"
    existing = {f["format_id"] for f in lib["formats"]}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def get(lib, format_id):
    for f in lib["formats"]:
        if f["format_id"] == format_id:
            return f
    raise KeyError(f"format not found: {format_id}")


def add(lib, entry):
    """entry without format_id gets a stable slug; collisions get -2, -3..."""
    entry = dict(entry)
    entry.setdefault("format_id", new_id(lib, entry["name"]))
    entry.setdefault("status", "candidate")
    entry.setdefault("our_stats", {"videos": 0, "wins": 0, "avg_multiplier": 0})
    if entry["status"] not in STATUSES:
        raise ValueError(f"bad status {entry['status']}")
    lib["formats"].append(entry)
    return entry["format_id"]


def update(lib, format_id, **fields):
    entry = get(lib, format_id)
    entry.update(fields)
    return entry


def set_status(lib, format_id, status):
    if status not in STATUSES:
        raise ValueError(f"bad status {status}")
    return update(lib, format_id, status=status)


def active(lib):
    """Formats usable for matching: candidate + proven (never retired)."""
    return [f for f in lib["formats"] if f["status"] in ("candidate", "proven")]
