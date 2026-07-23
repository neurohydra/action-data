"""``adp validate`` — check an ADP package against the canonical schemas.

Checks performed (each PASS/FAIL, non-zero exit on any hard FAIL):

1. manifest        adp.manifest.json validates against manifest.schema
2. session         the session part validates against session.schema
3. provenance      the provenance part validates against provenance.schema
4. timeline        a sample of rows validates against timeline.schema;
                   time_utc present on every sampled row; shadow / _raw
                   columns match the documented <source>_* patterns
5. integrity       every part carrying a hash re-hashes to the same value
                   (video parts deliberately carry no hash -> soft note)
6. tiers           tiers.light / tiers.heavy reference only declared parts

Timeline rows are read from parquet when pyarrow/pandas is available, else
from the CSV fallback via the stdlib csv module.
"""

from __future__ import annotations

import csv
import json
import random
import re
from pathlib import Path

from ._util import iso_utc, sha256_file, validator

# canonical (non-shadow) columns allowed bare in a timeline row
_CANON_COLS = {
    "time_utc", "lat", "lon", "alt_m", "speed_ms", "hr_bpm", "power_w",
    "cadence_rpm", "distance_m", "moving", "grit", "flow",
}
_SHADOW_RE = re.compile(
    r"^[a-z0-9]+_raw$|^[a-z0-9]+_(lat|lon)$|"
    r"^[a-z0-9]+_(alt_m|speed_ms|hr_bpm|power_w|cadence_rpm|distance_m)$"
)


class Check:
    __slots__ = ("name", "ok", "detail", "soft")

    def __init__(self, name, ok, detail="", soft=False):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.soft = soft


def _resolve(pkg_dir: Path, key: str) -> Path:
    p = Path(key)
    return p if p.is_absolute() else (pkg_dir / key)


def _load_part_json(pkg_dir: Path, parts: dict, name: str):
    part = parts.get(name)
    if part is None:
        return None, f"part '{name}' not declared"
    path = _resolve(pkg_dir, part["location"]["key"])
    if not path.is_file():
        return None, f"{name} payload missing at {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return None, f"{name} is not valid JSON: {e}"


def _schema_check(name, schema, doc, load_err) -> Check:
    if load_err:
        return Check(name, False, load_err)
    errs = sorted(validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errs:
        loc = "/".join(str(p) for p in errs[0].path) or "<root>"
        return Check(name, False, f"{len(errs)} error(s); first at {loc}: {errs[0].message}")
    return Check(name, True)


# ── timeline ────────────────────────────────────────────────────────────────

def _read_rows_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)
    return header, rows


def _coerce(header: list[str], raw: dict) -> dict:
    """CSV cell strings -> typed row: '' dropped, True/False -> bool, numeric
    -> float, time_utc normalized to 'T' form."""
    out = {}
    for col in header:
        val = raw.get(col)
        if val is None or val == "":
            continue
        if col == "time_utc":
            out[col] = iso_utc(val)
            continue
        if val in ("True", "False"):
            out[col] = val == "True"
            continue
        try:
            out[col] = float(val)
        except ValueError:
            out[col] = val
    return out


def _sample_indices(n: int, k: int = 12) -> list[int]:
    if n <= 0:
        return []
    idx = {0, n - 1}
    rnd = random.Random(0)
    while len(idx) < min(k, n):
        idx.add(rnd.randrange(n))
    return sorted(idx)


def _check_timeline(pkg_dir: Path, parts: dict) -> list[Check]:
    part = parts.get("timeline")
    if part is None:
        return [Check("timeline", False, "no timeline part declared")]

    path = _resolve(pkg_dir, part["location"]["key"])
    fmt = part.get("format")
    header = rows = None

    if fmt == "csv" and path.is_file():
        header, rows = _read_rows_csv(path)
    else:
        # parquet primary: try pyarrow, else fall back to declared csv
        try:
            import pyarrow.parquet as pq  # noqa: F401
            import pandas as pd
            df = pd.read_parquet(path)
            header = list(df.columns)
            df = df.astype(object).where(pd.notnull(df), None)
            rows = df.to_dict("records")
            # normalize time column to iso strings
            for r in rows:
                if r.get("time_utc") is not None:
                    r["time_utc"] = iso_utc(str(r["time_utc"]))
        except Exception:
            fb = part.get("fallback")
            if fb and fb.get("format") == "csv":
                fbp = _resolve(pkg_dir, fb["key"])
                if fbp.is_file():
                    header, rows = _read_rows_csv(fbp)
                    fmt = "csv"  # rows are strings -> csv coercion path
    if header is None:
        return [Check("timeline", False,
                      "could not read timeline (no pyarrow and no CSV fallback)")]

    checks = []

    # column-name contract: every column is canonical or a documented shadow
    bad = [c for c in header if c not in _CANON_COLS and not _SHADOW_RE.match(c)]
    checks.append(Check(
        "timeline.columns", not bad,
        f"unrecognized columns: {bad}" if bad else
        f"{len(header)} columns; shadow/_raw all match patterns"))

    # sample-row schema validation + time_utc presence
    tl_validator = validator("timeline")
    is_csv = fmt == "csv" or (isinstance(rows, list) and rows and
                              all(isinstance(v, str) for v in rows[0].values()))
    sample = _sample_indices(len(rows))
    n_err = 0
    first_err = ""
    missing_time = 0
    for i in sample:
        raw = rows[i]
        row = _coerce(header, raw) if is_csv else {
            k: v for k, v in raw.items() if v is not None}
        if "time_utc" in row and not is_csv:
            row["time_utc"] = iso_utc(str(row["time_utc"]))
        if "time_utc" not in row:
            missing_time += 1
        errs = list(tl_validator.iter_errors(row))
        if errs:
            n_err += 1
            if not first_err:
                loc = "/".join(str(p) for p in errs[0].path) or "<root>"
                first_err = f"row {i} @ {loc}: {errs[0].message}"

    checks.append(Check(
        "timeline.time_utc", missing_time == 0,
        f"{missing_time}/{len(sample)} sampled rows missing time_utc"
        if missing_time else f"present on all {len(sample)} sampled rows"))
    checks.append(Check(
        "timeline.rows", n_err == 0,
        first_err if n_err else f"{len(sample)} sampled rows valid"))
    return checks


# ── integrity + tiers ─────────────────────────────────────────────────────────

def _check_integrity(pkg_dir: Path, parts_list: list[dict]) -> list[Check]:
    checks = []
    hashed = 0
    for part in parts_list:
        name = part["part"]
        h = part.get("hash")
        if not h:
            if part.get("role") == "video":
                checks.append(Check(f"integrity.{name}", True,
                                    "no hash (heavy video, hashing skipped)",
                                    soft=True))
            continue
        path = _resolve(pkg_dir, part["location"]["key"])
        if not path.is_file():
            checks.append(Check(f"integrity.{name}", False,
                                f"referenced file missing: {path}"))
            continue
        actual = sha256_file(path)
        ok = actual == h
        hashed += 1
        checks.append(Check(f"integrity.{name}", ok,
                            "hash matches" if ok else
                            f"MISMATCH: manifest {h[:20]}… vs actual {actual[:20]}…"))
    if hashed == 0 and not checks:
        checks.append(Check("integrity", True, "no hashed parts", soft=True))
    return checks


def _check_tiers(manifest: dict) -> Check:
    names = {p["part"] for p in manifest["parts"]}
    tiers = manifest.get("tiers", {})
    referenced = list(tiers.get("light", [])) + list(tiers.get("heavy", []))
    dangling = [n for n in referenced if n not in names]
    return Check("tiers", not dangling,
                 f"dangling tier refs: {dangling}" if dangling else
                 f"light={len(tiers.get('light', []))} heavy={len(tiers.get('heavy', []))}, "
                 "all resolve")


# ── entry point ──────────────────────────────────────────────────────────────

def validate_package(target: str | Path) -> tuple[bool, list[Check]]:
    target = Path(target).resolve()
    if target.is_dir():
        pkg_dir = target
        manifest_path = target / "adp.manifest.json"
    else:
        manifest_path = target
        pkg_dir = target.parent
    if not manifest_path.is_file():
        return False, [Check("manifest", False, f"no manifest at {manifest_path}")]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, [Check("manifest", False, f"invalid JSON: {e}")]

    checks: list[Check] = []
    checks.append(_schema_check("manifest", "manifest", manifest, None))

    parts_list = manifest.get("parts", [])
    parts = {p["part"]: p for p in parts_list}

    session, s_err = _load_part_json(pkg_dir, parts, "session")
    checks.append(_schema_check("session", "session", session, s_err))

    prov, p_err = _load_part_json(pkg_dir, parts, "provenance")
    checks.append(_schema_check("provenance", "provenance", prov, p_err))

    # cross-part: session_ref consistency
    refs = {manifest.get("session_ref")}
    if session:
        refs.add(session.get("session_ref"))
    if prov:
        refs.add(prov.get("session_ref"))
    refs.discard(None)
    checks.append(Check("session_ref", len(refs) == 1,
                        f"consistent ({next(iter(refs))})" if len(refs) == 1
                        else f"mismatch across parts: {refs}"))

    # cross-part: provenance source hashes == raw part hashes
    if prov:
        mism = []
        for src in prov.get("sources", []):
            raw = parts.get(f"raw_{src['source']}")
            if raw and raw.get("hash") and raw["hash"] != src.get("hash"):
                mism.append(src["source"])
        checks.append(Check("provenance.raw_hashes", not mism,
                            f"mismatch: {mism}" if mism else
                            "raw part hashes match provenance sources", soft=True))

    checks.extend(_check_timeline(pkg_dir, parts))
    checks.extend(_check_integrity(pkg_dir, parts_list))
    checks.append(_check_tiers(manifest))

    ok = all(c.ok or c.soft for c in checks)
    return ok, checks
