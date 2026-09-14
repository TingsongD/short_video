"""Validate contract payloads against the frozen schemas in schemas/."""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS = ROOT / "schemas"


def load_schema(name):
    with open(SCHEMAS / name, encoding="utf-8") as f:
        return json.load(f)


def validate(data, name):
    """Raise jsonschema.ValidationError if data violates schemas/<name>."""
    jsonschema.validate(data, load_schema(name))
    return data
