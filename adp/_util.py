"""Shared helpers for the adp reference tooling: schema resolution, hashing,
and small time utilities. Stdlib + jsonschema only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

# Chunk size for streaming file hashes (raw FIT + derived tables are small; a
# video may be tens of GB, so never slurp the whole thing into memory).
_HASH_CHUNK = 1 << 20  # 1 MiB


def schemas_dir() -> Path:
    """Locate the canonical JSON Schemas.

    Works both from a source checkout (``<repo>/schemas``) and from an installed
    wheel (``adp/schemas``, force-included by pyproject).
    """
    here = Path(__file__).resolve().parent
    for cand in (here / "schemas", here.parent / "schemas"):
        if (cand / "manifest.schema.json").is_file():
            return cand
    raise FileNotFoundError("could not locate schemas/ (looked in adp/schemas and ../schemas)")


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """Load a schema by base name, e.g. 'manifest' -> manifest.schema.json."""
    path = schemas_dir() / f"{name}.schema.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    """A format-checking Draft 2020-12 validator for the named schema."""
    return Draft202012Validator(load_schema(name), format_checker=FormatChecker())


def sha256_file(path: Path) -> str:
    """Stream a file through sha256; return 'sha256:<hex>'."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def now_utc_iso() -> str:
    """Current time as an RFC3339/ISO-8601 UTC timestamp (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a space date/time separator."""
    return datetime.fromisoformat(ts.replace(" ", "T"))


def iso_utc(ts: str) -> str:
    """Normalize an ISO-8601 timestamp to a 'T'-separated form for date-time
    schema checks (leaves the offset untouched)."""
    return ts.replace(" ", "T")
