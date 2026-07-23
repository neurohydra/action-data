"""``adp wrap`` — turn an rfr producer ride folder into an ADP-light package.

Reads a ride folder (``manifest.json`` + ``derived/validation.json`` +
``derived/timeline.parquet|csv`` + ``fit/`` + ``video/``) and emits, under
``<out>/<ride>/``:

* ``session.json``     (layer 2, session.schema)
* ``provenance.json``  (layer 2, provenance.schema)
* ``adp.manifest.json``(manifest.schema) — indexes those plus the layer-1
  originals (FIT, video) referenced in place, never copied.

Heavy video is referenced by path + size only; its bytes are not hashed
(tens of GB). Small raw/derived files are hashed in full.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import ADP_VERSION
from ._util import iso_utc, now_utc_iso, parse_iso, sha256_file, validator

PRODUCER_FALLBACK = "randomfinnrides-pipeline"


class WrapError(Exception):
    """Raised when a ride folder cannot be wrapped (e.g. not yet processed)."""


# ── layer-2 part builders ────────────────────────────────────────────────────

# garmin session key -> canonical session_summary metric key
_GARMIN_METRICS = {
    "total_calories": "total_calories",
    "training_load_peak": "training_load",
    "total_grit": "total_grit",
    "avg_flow": "avg_flow",
    "num_laps": "num_laps",
    "enhanced_avg_respiration_rate": "avg_respiration_rate",
    "enhanced_max_respiration_rate": "max_respiration_rate",
    "enhanced_min_respiration_rate": "min_respiration_rate",
    "avg_heart_rate": "avg_heart_rate",
    "max_heart_rate": "max_heart_rate",
    "total_distance": "total_distance_m",
    "total_ascent": "total_ascent_m",
    "total_descent": "total_descent_m",
    "total_training_effect": "total_training_effect",
    "total_anaerobic_training_effect": "total_anaerobic_training_effect",
}
_BOSCH_METRICS = {
    "avg_power": "avg_power",
    "max_power": "max_power",
    "avg_cadence": "avg_cadence",
    "max_cadence": "max_cadence",
    "total_distance": "total_distance_m",
    "total_ascent": "total_ascent_m",
    "total_descent": "total_descent_m",
}
_SOURCE_METRIC_MAP = {"garmin": _GARMIN_METRICS, "bosch": _BOSCH_METRICS}


def _activity_hint(garmin_session: dict) -> str:
    sub = str(garmin_session.get("sub_sport", "")).lower()
    profile = str(garmin_session.get("sport_profile_name", "")).lower()
    sport = str(garmin_session.get("sport", "")).lower()
    if "e_bike" in sub or profile.startswith("emtb") or profile == "emtb":
        return "emtb"
    if "mountain" in sub or "mtb" in profile:
        return "mtb"
    if sport == "cycling":
        return "cycling"
    return sport or "unknown"


def _device_string(source: str, file_id: dict) -> str:
    manuf = str(file_id.get("manufacturer", source))
    product = file_id.get("garmin_product") or file_id.get("product")
    serial = file_id.get("serial_number")
    parts = [manuf]
    if product and product != 0:
        parts.append(str(product))
    dev = " ".join(parts)
    if serial:
        dev = f"{dev} #{serial}"
    return dev


def _source_summaries(sources: dict) -> list[dict]:
    summaries = []
    for source, block in sources.items():
        session = block.get("session", {})
        mapping = _SOURCE_METRIC_MAP.get(source, {})
        metrics = {}
        for raw_key, out_key in mapping.items():
            val = session.get(raw_key)
            if val is None:
                continue
            if out_key == "num_laps":
                val = int(val)
            metrics[out_key] = val
        if not metrics:
            continue
        summary = {"source": source, "metrics": metrics}
        dev = _device_string(source, block.get("file_id", {}))
        if dev:
            summary["device"] = dev
        if session.get("sport"):
            summary["sport"] = session["sport"]
        if session.get("sub_sport"):
            summary["sub_sport"] = session["sub_sport"]
        summaries.append(summary)
    return summaries


def build_session(manifest: dict, session_ref: str) -> dict:
    tl = manifest["timeline"]
    start = iso_utc(tl["start_utc"])
    end = iso_utc(tl["end_utc"])
    duration = (parse_iso(end) - parse_iso(start)).total_seconds()
    sources = manifest.get("sources", {})
    garmin_session = sources.get("garmin", {}).get("session", {})
    session = {
        "session_ref": session_ref,
        "started_utc": start,
        "ended_utc": end,
        "duration_s": duration,
        "timezone": manifest.get("timezone", "UTC"),
        "producer": {
            "name": PRODUCER_FALLBACK,
            "version": manifest.get("pipeline_version", "0.0.0"),
        },
        "source_summaries": _source_summaries(sources),
    }
    hint = _activity_hint(garmin_session)
    if hint:
        session["activity_hint"] = hint
    return session


_CANON_ALLOWED = {
    "source", "fallback", "span_start_utc", "span_end_utc", "span_s",
    "missing_s", "coverage_pct", "longest_gap_s", "gaps",
}


def build_provenance(manifest: dict, validation: dict, ride_dir: Path,
                     session_ref: str) -> tuple[dict, dict[str, str]]:
    """Return (provenance dict, {source: fit_hash}). The hash map lets the
    manifest's raw parts reuse the exact per-source content hashes."""
    sources_out = []
    fit_hashes: dict[str, str] = {}
    for source, block in manifest.get("sources", {}).items():
        fit_path = ride_dir / "fit" / f"{source}.fit"
        entry = {"source": source}
        dev = _device_string(source, block.get("file_id", {}))
        if dev:
            entry["device"] = dev
        if fit_path.is_file():
            entry["file"] = f"fit/{source}.fit"
            h = sha256_file(fit_path)
            entry["hash"] = h
            fit_hashes[source] = h
        else:
            # honest: no raw bytes on disk to hash. hash is REQUIRED by schema,
            # so a source with no FIT file cannot be represented — skip it.
            continue
        span = validation.get(f"{source}_span")
        if span:
            window = {
                "start_utc": iso_utc(span["start_utc"]),
                "end_utc": iso_utc(span["end_utc"]),
            }
            if "raw_points" in span:
                window["raw_points"] = int(span["raw_points"])
            entry["window"] = window
        entry["clock_sync_offset_s"] = 0.0  # rfr aligns on absolute FIT UTC
        sources_out.append(entry)

    canonical = {}
    for col, rep in validation.get("canonical", {}).items():
        out = {"source": rep.get("primary")}
        for k, v in rep.items():
            if k in _CANON_ALLOWED and k not in ("source",):
                out[k] = v
        canonical[col] = out

    provenance = {
        "session_ref": session_ref,
        "sources": sources_out,
        "canonical": canonical,
    }
    return provenance, fit_hashes


# ── manifest assembly ────────────────────────────────────────────────────────

def _part(name, layer, role, store, key, fmt, *, bytes_=None, hash_=None,
          fallback=None) -> dict:
    part = {
        "part": name,
        "layer": layer,
        "role": role,
        "location": {"store": store, "key": key},
        "format": fmt,
    }
    if fallback is not None:
        part["fallback"] = fallback
    if bytes_ is not None:
        part["bytes"] = int(bytes_)
    if hash_ is not None:
        part["hash"] = hash_
    return part


def build_manifest(manifest_in: dict, ride_dir: Path, pkg_dir: Path,
                   session_ref: str, session_bytes: int, session_hash: str,
                   prov_bytes: int, prov_hash: str,
                   fit_hashes: dict[str, str]) -> dict:
    parts: list[dict] = []
    light: list[str] = []
    heavy: list[str] = []

    # session (materialized, light)
    parts.append(_part("session", 2, "session", "default", "session.json",
                        "json", bytes_=session_bytes, hash_=session_hash))
    light.append("session")

    # timeline (referenced in place, light). parquet primary + csv fallback.
    derived = ride_dir / "derived"
    parquet = derived / "timeline.parquet"
    csv = derived / "timeline.csv"
    if parquet.is_file():
        fb = None
        if csv.is_file():
            fb = {"format": "csv", "key": csv.resolve().as_posix()}
        parts.append(_part("timeline", 2, "timeline", "default",
                            parquet.resolve().as_posix(), "parquet",
                            bytes_=parquet.stat().st_size,
                            hash_=sha256_file(parquet), fallback=fb))
        light.append("timeline")
    elif csv.is_file():
        parts.append(_part("timeline", 2, "timeline", "default",
                            csv.resolve().as_posix(), "csv",
                            bytes_=csv.stat().st_size, hash_=sha256_file(csv)))
        light.append("timeline")

    # provenance (materialized, light)
    parts.append(_part("provenance", 2, "provenance", "default",
                        "provenance.json", "json", bytes_=prov_bytes,
                        hash_=prov_hash))
    light.append("provenance")

    # raw FIT (referenced in place, heavy) — reuse provenance content hashes
    for source in manifest_in.get("sources", {}):
        fit_path = ride_dir / "fit" / f"{source}.fit"
        if not fit_path.is_file():
            continue
        name = f"raw_{source}"
        parts.append(_part(name, 1, "raw", "default",
                           fit_path.resolve().as_posix(), "fit",
                           bytes_=fit_path.stat().st_size,
                           hash_=fit_hashes.get(source)))
        heavy.append(name)

    # video (referenced in place, heavy) — NOT hashed (tens of GB)
    clips = manifest_in.get("clips", [])
    for i, clip in enumerate(clips):
        vid = ride_dir / "video" / clip["file"]
        if not vid.is_file():
            continue
        name = "video" if len(clips) == 1 else f"video_{i + 1}"
        parts.append(_part(name, 1, "video", "default",
                           vid.resolve().as_posix(), "mp4",
                           bytes_=vid.stat().st_size))
        heavy.append(name)

    return {
        "adp_version": ADP_VERSION,
        "session_ref": session_ref,
        "generated_utc": now_utc_iso(),
        "producer": {
            "name": PRODUCER_FALLBACK,
            "version": manifest_in.get("pipeline_version", "0.0.0"),
        },
        "timezone": manifest_in.get("timezone", "UTC"),
        "refine_version": manifest_in.get("pipeline_version", "unknown"),
        "scrub": {"applied": False},
        "parts": parts,
        "tiers": {"light": light, "heavy": heavy},
    }


# ── entry point ──────────────────────────────────────────────────────────────

def wrap(ride_folder: str | Path, out_dir: str | Path = "out") -> Path:
    ride_dir = Path(ride_folder).resolve()
    if not ride_dir.is_dir():
        raise WrapError(f"not a directory: {ride_dir}")

    manifest_path = ride_dir / "manifest.json"
    validation_path = ride_dir / "derived" / "validation.json"
    if not manifest_path.is_file():
        raise WrapError(
            f"{ride_dir.name}: no manifest.json — ride is not processed by the "
            "producer (rfr) yet; nothing to wrap."
        )
    if not validation_path.is_file():
        raise WrapError(f"{ride_dir.name}: missing derived/validation.json")

    manifest_in = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))

    session_ref = str(uuid.uuid4())
    pkg_dir = Path(out_dir).resolve() / ride_dir.name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    session = build_session(manifest_in, session_ref)
    provenance, fit_hashes = build_provenance(manifest_in, validation, ride_dir,
                                              session_ref)

    session_path = pkg_dir / "session.json"
    prov_path = pkg_dir / "provenance.json"
    session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    manifest = build_manifest(
        manifest_in, ride_dir, pkg_dir, session_ref,
        session_path.stat().st_size, sha256_file(session_path),
        prov_path.stat().st_size, sha256_file(prov_path),
        fit_hashes,
    )
    (pkg_dir / "adp.manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # fail fast on a malformed self-produced manifest
    errs = sorted(validator("manifest").iter_errors(manifest),
                  key=lambda e: e.path)
    if errs:
        raise WrapError(
            f"{ride_dir.name}: produced manifest fails its own schema: "
            f"{errs[0].message}"
        )
    return pkg_dir
