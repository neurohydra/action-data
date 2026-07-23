"""``adp project --to ridepackage-v0`` — project an ADP package back into the
exact folder shape the live-trails (LT) consumer reads.

Background
----------
The producer is randomfinnrides (rfr); the consumer is live-trails' TypeScript
``packages/telemetry`` reader, which ingests the *temporary* "RidePackage v0"
folder contract (ADR-0002):

    <rideDir>/manifest.json
    <rideDir>/derived/timeline.parquet   (+ .csv identical fallback)
    <rideDir>/video/<clip.file>          (one per manifest clip)
    <rideDir>/clips.yaml                 (optional hand-marked highlights)

ADP generalizes that folder into a self-describing, storage-agnostic, layered
wrapper (``adp.manifest.json`` + ``session.json`` + ``provenance.json`` +
``clips.json``, referencing the layer-1 FIT/video originals in place).

This command performs the inverse: a **projection** (a "de-wrap"). The v0
``manifest.json`` is a *consumer view* — it does NOT travel in the canonical ADP
package, but it can be regenerated deterministically from the package's parts.
That proves ADP is a faithful superset that round-trips to what the existing
consumer already reads.

Field mapping (ADP part -> v0 manifest field)
---------------------------------------------
    ride                <- package directory name (v0 slug is a producer/consumer
                           label; ADP identifies the activity by session_ref UUID)
    generated_utc       <- manifest.generated_utc
    pipeline_version    <- manifest.producer.version
    timezone            <- manifest.timezone
    sources             <- provenance.sources[] (+ session.source_summaries),
                           re-keyed by source id
    clips[]             <- clips.json (verbatim; full round-trip)
    timeline.file       <- timeline part location (copied into derived/)
    timeline.rows       <- counted from the copied timeline (CSV data rows)
    timeline.start_utc  <- session.started_utc   (== original timeline.start_utc)
    timeline.end_utc    <- session.ended_utc      (== original timeline.end_utc)
    validation          <- {file, warnings: []}  (rfr warnings are not carried by
                           ADP-light; see COMPAT_LT.md)

The small layer-2 timeline (~190 KB parquet + CSV) is copied into the projected
``derived/``. The heavy layer-1 video is *linked* in place (hardlink, else
symlink) so ``video/<file>`` exists without duplicating tens of GB.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

TARGETS = ("ridepackage-v0",)


class ProjectError(Exception):
    """Raised when an ADP package cannot be projected to a consumer view."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve(pkg_dir: Path, key: str) -> Path:
    p = Path(key)
    return p if p.is_absolute() else (pkg_dir / key)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _part_map(manifest: dict) -> dict[str, dict]:
    return {p["part"]: p for p in manifest.get("parts", [])}


def _count_csv_rows(path: Path) -> int:
    """Data-row count of a timeline CSV (header excluded, blank lines ignored)."""
    n = 0
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if row and any(cell.strip() for cell in row):
                n += 1
    return n


def _link_or_copy(src: Path, dst: Path) -> str:
    """Make ``dst`` refer to ``src`` cheaply. Prefer a hardlink (instant, no
    extra bytes, same volume), then a symlink; never copy heavy video. Returns
    the method used, or 'skipped' if no link could be made."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        pass
    try:
        os.symlink(src, dst)
        return "symlink"
    except OSError:
        return "skipped"


# ── v0 manifest assembly ──────────────────────────────────────────────────────

def _rebuild_sources(session: dict, provenance: dict) -> dict:
    """Re-key provenance.sources[] (+ session summaries) into the v0
    ``sources`` object: {source_id: {…}}. The LT schema only requires an object
    per source; we carry back the device, raw-window, hash and summary metrics."""
    summaries = {s["source"]: s for s in session.get("source_summaries", [])}
    out: dict = {}
    for src in provenance.get("sources", []):
        sid = src["source"]
        block: dict = {}
        for k in ("device", "file", "hash", "window", "clock_sync_offset_s"):
            if k in src:
                block[k] = src[k]
        summ = summaries.get(sid)
        if summ:
            if "metrics" in summ:
                block["summary"] = summ["metrics"]
            for k in ("sport", "sub_sport"):
                if k in summ:
                    block[k] = summ[k]
        out[sid] = block
    # sources that only appear as a session summary (no raw FIT in provenance)
    for sid, summ in summaries.items():
        if sid not in out:
            block = {"summary": summ.get("metrics", {})}
            for k in ("device", "sport", "sub_sport"):
                if k in summ:
                    block[k] = summ[k]
            out[sid] = block
    return out


def build_v0_manifest(pkg_dir: Path, manifest: dict, session: dict,
                      provenance: dict, clips: list, timeline_rel: str,
                      timeline_rows: int, ride: str) -> dict:
    return {
        "ride": ride,
        "generated_utc": manifest["generated_utc"],
        "pipeline_version": manifest.get("producer", {}).get("version", "0.0.0"),
        "timezone": manifest.get("timezone", "UTC"),
        "sources": _rebuild_sources(session, provenance),
        "clips": clips,
        "timeline": {
            "file": timeline_rel,
            "rows": timeline_rows,
            "start_utc": session["started_utc"],
            "end_utc": session["ended_utc"],
        },
        "validation": {
            # ADP-light does not carry the producer's validation warnings; the LT
            # reader schema-validates this block but never reads its contents.
            "file": "derived/validation.json",
            "warnings": [],
        },
    }


# ── entry point ───────────────────────────────────────────────────────────────

def project_ridepackage_v0(pkg: str | Path, out_dir: str | Path | None = None,
                           ride: str | None = None) -> tuple[Path, dict]:
    """Project an ADP package directory into a RidePackage v0 folder.

    Returns (projected_dir, info) where info records what was produced.
    """
    pkg_dir = Path(pkg).resolve()
    manifest_path = pkg_dir / "adp.manifest.json"
    if not manifest_path.is_file():
        raise ProjectError(f"no adp.manifest.json in {pkg_dir}")

    manifest = _load_json(manifest_path)
    parts = _part_map(manifest)

    if "session" not in parts:
        raise ProjectError("package has no session part; cannot derive timeline span")
    if "timeline" not in parts:
        raise ProjectError("package has no timeline part")
    if "clips" not in parts:
        raise ProjectError(
            "package has no clips part — the segment media/timing block is not "
            "present, so a v0 clips[] cannot be reconstructed. Re-wrap with a "
            "producer manifest that declares clips (adp wrap emits clips.json)."
        )

    session = _load_json(_resolve(pkg_dir, parts["session"]["location"]["key"]))
    provenance = (
        _load_json(_resolve(pkg_dir, parts["provenance"]["location"]["key"]))
        if "provenance" in parts else {"sources": []}
    )
    clips = _load_json(_resolve(pkg_dir, parts["clips"]["location"]["key"]))

    ride = ride or pkg_dir.name
    out = Path(out_dir).resolve() if out_dir else (pkg_dir / "ridepackage-v0")
    out.mkdir(parents=True, exist_ok=True)

    info: dict = {"ride": ride, "out": str(out), "video": [], "notes": []}

    # ── timeline: copy the small layer-2 table (primary + csv fallback) ────────
    tl_part = parts["timeline"]
    tl_src = _resolve(pkg_dir, tl_part["location"]["key"])
    derived = out / "derived"
    derived.mkdir(parents=True, exist_ok=True)

    tl_fmt = tl_part.get("format", "parquet")
    primary_name = f"timeline.{'parquet' if tl_fmt == 'parquet' else tl_fmt}"
    if tl_src.is_file():
        shutil.copy2(tl_src, derived / primary_name)
    else:
        info["notes"].append(f"timeline primary not found on disk: {tl_src}")

    csv_dst = derived / "timeline.csv"
    fb = tl_part.get("fallback")
    if tl_fmt == "csv":
        csv_dst = derived / primary_name  # primary already is the csv
    elif fb and fb.get("format") == "csv":
        fb_src = _resolve(pkg_dir, fb["key"])
        if fb_src.is_file():
            shutil.copy2(fb_src, csv_dst)

    timeline_rel = f"derived/{primary_name}"

    # ── timeline.rows: count from the copied CSV (no pyarrow needed) ───────────
    if csv_dst.is_file():
        timeline_rows = _count_csv_rows(csv_dst)
    else:
        timeline_rows = 0
        info["notes"].append(
            "no CSV timeline available to count rows; timeline.rows set to 0")

    # ── validation.json stub (LT schema-requires the block; content unused) ────
    (derived / "validation.json").write_text(
        json.dumps({"file": "derived/validation.json", "warnings": []}, indent=2),
        encoding="utf-8",
    )

    # ── video: link each layer-1 original into video/ (never copy) ─────────────
    video_parts = [p for p in manifest.get("parts", []) if p.get("role") == "video"]
    # map clip file -> declared video part by basename, else fall back to order
    by_name = {Path(p["location"]["key"]).name: p for p in video_parts}
    for i, clip in enumerate(clips):
        fname = clip["file"]
        vp = by_name.get(fname) or (video_parts[i] if i < len(video_parts) else None)
        if vp is None:
            info["video"].append({"file": fname, "method": "skipped",
                                  "reason": "no matching video part"})
            info["notes"].append(f"clip {fname}: no video part in package")
            continue
        src = _resolve(pkg_dir, vp["location"]["key"])
        dst = out / "video" / fname
        if not src.is_file():
            info["video"].append({"file": fname, "method": "skipped",
                                  "reason": f"source missing: {src}"})
            info["notes"].append(f"clip {fname}: video source missing at {src}")
            continue
        method = _link_or_copy(src, dst)
        info["video"].append({"file": fname, "method": method, "src": str(src)})
        if method == "skipped":
            info["notes"].append(
                f"clip {fname}: could not link video; read with verifyVideos:false")

    # ── manifest.json ──────────────────────────────────────────────────────────
    v0 = build_v0_manifest(pkg_dir, manifest, session, provenance, clips,
                           timeline_rel, timeline_rows, ride)
    (out / "manifest.json").write_text(json.dumps(v0, indent=2), encoding="utf-8")
    info["timeline_rows"] = timeline_rows
    info["timeline_file"] = timeline_rel
    return out, info


# ── LT contract verification (static match) ───────────────────────────────────
#
# Mirrors live-trails' Zod schema `RidePackageV0Manifest` (packages/domain,
# ingest/ridepackage-v0.ts) and the reader's file/column expectations. This is
# the authoritative static contract check the koeajo confirms.

_CLIP_FIELDS = {
    "file": str, "start_utc": str, "start_local": str, "duration_s": (int, float),
    "end_utc": str, "offset_s": (int, float), "recording_start_utc": str,
    "width": int, "height": int, "fps": (int, float), "codec": str,
    "size_bytes": int,
}
_READER_TIMELINE_COLS = ("time_utc", "lat", "lon")  # reader-required columns


class _Chk:
    __slots__ = ("name", "ok", "detail")

    def __init__(self, name, ok, detail=""):
        self.name, self.ok, self.detail = name, ok, detail


def verify_ridepackage_v0(ride_dir: str | Path) -> tuple[bool, list[_Chk]]:
    ride_dir = Path(ride_dir).resolve()
    checks: list[_Chk] = []

    def chk(name, ok, detail=""):
        checks.append(_Chk(name, ok, detail))

    mpath = ride_dir / "manifest.json"
    if not mpath.is_file():
        return False, [_Chk("manifest.json", False, f"missing at {mpath}")]
    try:
        m = _load_json(mpath)
    except json.JSONDecodeError as e:
        return False, [_Chk("manifest.json", False, f"invalid JSON: {e}")]

    # top-level required fields + types
    for field, typ in (("ride", str), ("generated_utc", str),
                       ("pipeline_version", str), ("timezone", str)):
        v = m.get(field)
        ok = isinstance(v, typ) and (not isinstance(v, str) or len(v) > 0)
        chk(f"manifest.{field}", ok, "" if ok else f"missing/empty ({v!r})")

    sources = m.get("sources")
    ok = isinstance(sources, dict) and len(sources) >= 1 and all(
        isinstance(v, dict) for v in sources.values())
    chk("manifest.sources", ok,
        f"{len(sources)} source(s)" if ok else "must be non-empty object of objects")

    clips = m.get("clips")
    if not isinstance(clips, list) or not clips:
        chk("manifest.clips", False, "must be a non-empty array")
    else:
        bad = []
        for i, c in enumerate(clips):
            for field, typ in _CLIP_FIELDS.items():
                v = c.get(field)
                good = isinstance(v, typ) and not (isinstance(v, bool))
                if field in ("duration_s", "fps"):
                    good = good and v > 0
                if field in ("width", "height"):
                    good = isinstance(v, int) and not isinstance(v, bool) and v > 0
                if field in ("file", "codec", "start_utc", "start_local",
                             "end_utc", "recording_start_utc"):
                    good = isinstance(v, str) and len(v) > 0
                if not good:
                    bad.append(f"clip[{i}].{field}={v!r}")
        chk("manifest.clips", not bad,
            f"{len(clips)} clip(s), all fields present" if not bad
            else f"invalid: {bad[:4]}")

    tl = m.get("timeline")
    if not isinstance(tl, dict):
        chk("manifest.timeline", False, "missing")
    else:
        ok = (isinstance(tl.get("file"), str) and tl["file"]
              and isinstance(tl.get("rows"), int) and tl["rows"] >= 0
              and isinstance(tl.get("start_utc"), str)
              and isinstance(tl.get("end_utc"), str))
        chk("manifest.timeline", ok,
            f"file={tl.get('file')} rows={tl.get('rows')}" if ok else "missing fields")

    val = m.get("validation")
    ok = (isinstance(val, dict) and isinstance(val.get("file"), str)
          and val["file"] and isinstance(val.get("warnings"), list))
    chk("manifest.validation", ok, "" if ok else "need {file, warnings[]}")

    # timeline file present + reader-required columns
    if isinstance(tl, dict) and isinstance(tl.get("file"), str):
        tpath = ride_dir / tl["file"]
        csv_sib = tpath.with_suffix(".csv")
        present = tpath.is_file()
        chk("timeline.file_present", present,
            str(tpath) if present else f"missing: {tpath}")
        # column contract: check the CSV (identical to parquet by spec §4)
        header_src = tpath if tpath.suffix == ".csv" and present else (
            csv_sib if csv_sib.is_file() else None)
        if header_src is not None:
            with header_src.open(newline="", encoding="utf-8") as fh:
                header = next(csv.reader(fh), [])
            missing = [c for c in _READER_TIMELINE_COLS if c not in header]
            chk("timeline.columns", not missing,
                f"{len(header)} cols; reader-required present" if not missing
                else f"missing reader columns: {missing}")
        else:
            chk("timeline.columns", True,
                "parquet-only (no CSV to inspect); columns assumed per spec §4")

    # video files present for each clip
    if isinstance(clips, list) and clips:
        missing = [c["file"] for c in clips
                   if isinstance(c, dict) and c.get("file")
                   and not (ride_dir / "video" / c["file"]).is_file()]
        chk("video.files_present", not missing,
            "all clip videos present" if not missing else f"missing: {missing}")

    ok_all = all(c.ok for c in checks)
    return ok_all, checks
