"""Every schema in ``schemas/`` is valid JSON and a well-formed draft 2020-12
metaschema."""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from conftest import SCHEMAS_DIR

SCHEMA_FILES = sorted(SCHEMAS_DIR.glob("*.schema.json"))


def test_schemas_dir_is_populated():
    # guard against an empty glob silently making the parametrized tests vacuous
    assert SCHEMA_FILES, f"no *.schema.json found under {SCHEMAS_DIR}"
    names = {p.name for p in SCHEMA_FILES}
    for expected in (
        "manifest.schema.json",
        "session.schema.json",
        "provenance.schema.json",
        "timeline.schema.json",
        "clips.schema.json",
        "enrichment.schema.json",
        "storage-map.schema.json",
    ):
        assert expected in names, f"missing schema file: {expected}"


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_parses(schema_path):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert isinstance(schema, dict)
    assert schema.get("$schema", "").endswith("2020-12/schema")


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_passes_metaschema(schema_path):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # raises SchemaError if the schema itself is malformed
    Draft202012Validator.check_schema(schema)
