"""Thin wrapper so domain code never imports jsonschema directly."""
import json

import jsonschema


def jsonschema_validate(payload, schema_path):
    """Return a list of human-readable problems; empty means valid."""
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    v = jsonschema.Draft202012Validator(schema)
    return [".".join(str(p) for p in e.absolute_path) + ": " + e.message
            for e in sorted(v.iter_errors(payload),
                            key=lambda e: list(e.absolute_path))]
