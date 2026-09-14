"""G0 / contract freeze: every sample fixture validates against its frozen schema,
and the negative fixture is correctly rejected (BUILD_PLAN.md §2)."""
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
CONTRACTS = ROOT / "tests" / "fixtures" / "contracts"

# sample fixture -> schema it must satisfy
VALID_CASES = {
    "niche_report.sample.json": "niche_report.schema.json",
    "scored_ideas.sample.json": "scored_ideas.schema.json",
    "format_library.sample.json": "format_library.schema.json",
    "shot_list.sample.json": "shot_list.schema.json",
    "asset_manifest.sample.json": "asset_manifest.schema.json",
    "mpt_task.sample.json": "mpt_task.schema.json",
    "publish_record.sample.json": "publish_record.schema.json",
    "readback.sample.json": "readback.schema.json",
    "hooks_bank.sample.json": "hooks_bank.schema.json",
}

INVALID_CASES = {
    "scored_ideas.invalid.json": "scored_ideas.schema.json",
}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("fixture,schema", sorted(VALID_CASES.items()))
def test_valid_fixtures_pass(fixture, schema):
    data = _load(CONTRACTS / fixture)
    jsonschema.validate(data, _load(SCHEMAS / schema))


@pytest.mark.parametrize("fixture,schema", sorted(INVALID_CASES.items()))
def test_invalid_fixtures_are_rejected(fixture, schema):
    data = _load(CONTRACTS / fixture)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, _load(SCHEMAS / schema))


def test_all_schemas_are_valid_meta_schemas():
    """Every frozen schema must itself be a valid Draft 2020-12 schema."""
    for schema_file in sorted(SCHEMAS.glob("*.schema.json")):
        jsonschema.Draft202012Validator.check_schema(_load(schema_file))


def test_fixture_coverage_matches_schema_set():
    """Every frozen schema has at least one valid sample fixture (nothing untestable)."""
    covered = set(VALID_CASES.values())
    on_disk = {p.name for p in SCHEMAS.glob("*.schema.json")}
    assert on_disk == covered, f"schemas without fixtures: {on_disk - covered}"
