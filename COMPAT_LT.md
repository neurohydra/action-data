# Consumer koeajo — does an ADP package round-trip to the live-trails read head?

The producer-side koeajo (`REPORT.md`) proved rfr ride folders `adp wrap` +
`adp validate` cleanly. This is the **other direction**: can live-trails' (LT)
consumer — its TypeScript `packages/telemetry` reader — consume an ADP package?

**Answer: yes.** An ADP package round-trips to the exact folder shape the LT
reader ingests, and the reader reads it. Both a **static contract match** and a
**live run through the real built LT reader** were achieved against current
data (`2026-07-13_lohjanharjun-mtb`, a multi-source eMTB ride: Garmin + Bosch).

One blocking gap was found and closed with a **clearly additive** change:
`adp wrap` now emits the manifest's already-reserved `role:"clips"` part
(`clips.json`), so the per-segment media/timing block travels in the light core.
No JSON Schema file was modified. Two benign lossy fields remain (both
schema-required-but-reader-unused) and are noted below.

---

## 1. The LT reader contract (as found, read-only)

Source: `D:/MTB/live-trails/packages/telemetry/src/*` and the v0 Zod schema
`packages/domain/src/ingest/ridepackage-v0.ts` (ADR-0002 — the RidePackage v0
format is explicitly **temporary**; only this package may import it).

Entry point: `readRidePackage(rideDir, options)` → domain `RidePackage`.

### Files expected under `rideDir/`

| Path | Required | Read by | Notes |
|------|----------|---------|-------|
| `manifest.json` | yes | `manifest.ts` | validated against `RidePackageV0Manifest` (Zod) |
| `<manifest.timeline.file>` (e.g. `derived/timeline.parquet`) | yes | `timeline.ts` | parquet primary; sibling/`derived/timeline.csv` is an identical fallback |
| `video/<clip.file>` (one per clip) | yes* | `ride-package-reader.ts` | existence checked when `verifyVideos` (default `true`) |
| `clips.yaml` | no | `highlights.ts` | optional hand-marked highlights; absent → field omitted |

### `manifest.json` — required fields (Zod `RidePackageV0Manifest`, `.passthrough()`)

- `ride` (non-empty string) → becomes `ride.id` default + slug
- `generated_utc` (ISO date-time) — **schema-required; never read by the reader**
- `pipeline_version` (non-empty string) — schema-required; not read
- `timezone` (non-empty string) → `ride.timezone`
- `sources` (object, ≥1 key, each value an object) — schema-required; not read
- `clips[]` (≥1). Each clip requires **all** of: `file`, `start_utc`,
  `start_local`, `duration_s` (>0), `end_utc`, `offset_s`, `recording_start_utc`,
  `width` (int>0), `height` (int>0), `fps` (>0), `codec`, `size_bytes` (int≥0).
  → mapped field-for-field into domain `VideoAsset`.
- `timeline` = `{ file, rows (int≥0), start_utc, end_utc }`. `timeline.start_utc`
  → `ride.capturedAt`; `timeline.file` locates the timeline. `rows` is
  schema-required but not read.
- `validation` = `{ file, warnings[] }` — schema-required; **never read**.

### Timeline columns + units (read per row → `TrackPoint`)

Reader-required: `time_utc` (ISO; space separator tolerated), `lat`, `lon`
(degrees). Rows without lat/lon/time are **dropped** (a `TrackPoint` needs a GPS
fix). Optional, mapped by name: `alt_m` (m), `speed_ms` (m/s), `hr_bpm`,
`power_w` (W), `cadence_rpm`, `distance_m` (m), `grit`, `flow`, `moving` (bool).
Source-shadow columns (`bosch_*`, `garmin_raw`, …) are ignored. A `Track`
requires ≥2 points.

---

## 2. Field-by-field ADP → LT mapping

ADP-light package = `adp.manifest.json` + `session.json` + `provenance.json` +
`clips.json` (new), referencing layer-1 FIT/video in place.

| LT v0 field | Source in ADP package | Transform |
|-------------|-----------------------|-----------|
| `ride` | package directory name | v0 slug is a producer/consumer label; ADP identifies the activity by `session_ref` (UUID). Slug is not a canonical ADP fact → taken from the package dir. |
| `generated_utc` | `adp.manifest.generated_utc` | direct — but this is the **ADP wrap time**, not the producer's original manifest timestamp (see §5). |
| `pipeline_version` | `adp.manifest.producer.version` | rename |
| `timezone` | `adp.manifest.timezone` | direct |
| `sources{}` | `provenance.sources[]` (+ `session.source_summaries[]`) | re-key list → object by `source` id; carry device / window / hash / summary metrics |
| `clips[]` | `clips.json` | **verbatim** — full byte-identical round-trip |
| `timeline.file` | `timeline` part `location.key` | copy the ~190 KB table into `derived/`; set relative path |
| `timeline.rows` | (not carried) | **re-derived**: count data rows of the copied CSV |
| `timeline.start_utc` | `session.started_utc` | equal to the original `timeline.start_utc` by construction |
| `timeline.end_utc` | `session.ended_utc` | equal to the original `timeline.end_utc` |
| `validation` | (not carried) | stub `{file, warnings: []}` — schema-valid; contents unused by reader |
| `video/<file>` | video part `location.key` | hardlink (else symlink) — never copy tens of GB |
| `clips.yaml` | (not applicable) | ADP-light carries no highlights; omitted (reader treats absent as none) |

### The one gap, and the fix (adopted)

Before this koeajo, `adp wrap` did **not** carry the clip block at all — the ADP
video part records only `location.key` + `bytes`. So `start_utc`, `start_local`,
`duration_s`, `end_utc`, `offset_s`, `recording_start_utc`, `width`, `height`,
`fps`, `codec` — every clip field except `file`/`size_bytes` — was dropped, and
a v0 `clips[]` could not be reconstructed. That made ADP-light **not** a faithful
superset of the consumer contract.

Fix: `adp wrap` now materializes `clips.json` and indexes it as a layer-2
`role:"clips"` part in `tiers.light`. This is judged clearly-correct-and-additive
because (a) the manifest schema **already reserves** `role:"clips"` in its enum
and its `tiers.light` description; (b) it is purely additive — a new part, a new
`tiers.light` entry, nothing existing changed; (c) it uses data the producer
already emits — the clip records are stored **verbatim**, no derivation, no
renaming, no guessing. No JSON Schema file was modified (see §5 for the parked
canonical-clips-schema question).

---

## 3. The projection — `adp project --to ridepackage-v0`

New subcommand (`adp/project.py`, wired into `adp/cli.py`). The v0 `manifest.json`
is a **consumer view**: it does not travel in the canonical package, but is
regenerated deterministically from the package's parts. The projection:

- writes `manifest.json` per the mapping in §2;
- copies the small layer-2 timeline (parquet primary + CSV fallback) into
  `derived/`, and a `derived/validation.json` stub;
- **links** (hardlink → symlink) each layer-1 video into `video/` — no bytes copied;
- counts `timeline.rows` from the CSV (no `pyarrow` needed).

`--verify` checks the projected folder against the LT contract from §1 (mirrors
the Zod `RidePackageV0Manifest` field-for-field, plus timeline-file presence,
reader-required columns, and per-clip video presence).

---

## 4. Proof against current data — `2026-07-13_lohjanharjun-mtb`

```
adp wrap    "D:/MTB/rides/2026-07-13_lohjanharjun-mtb" -o out   # now emits clips.json
adp validate out/2026-07-13_lohjanharjun-mtb                    # OK (0 hard fail); integrity.clips PASS
adp project  out/2026-07-13_lohjanharjun-mtb --to ridepackage-v0 --verify
```

### Static contract match — ACHIEVED

`--verify` reports **MATCH (0 failures)**: every top-level field, all 12 clip
fields, the timeline block, `validation`, timeline-file presence, reader-required
columns (`time_utc`/`lat`/`lon` present among 20 cols), and the clip video (present
via hardlink). Direct compare of projected vs. original rfr `manifest.json`:

- `ride`, `pipeline_version`, `timezone` — equal
- `clips[]` — **byte-identical**
- `timeline.rows` 3438 == 3438; `timeline.file`, `start_utc`, `end_utc` — equal
- `sources` — same keys (`garmin`, `bosch`), each an object

### Live reader run — ACHIEVED

The real built LT reader (`packages/telemetry/dist/index.js`, already built; no
install, no build, no LT source change) was pointed at the projected folder from
a runner outside the LT repo. `readRidePackage(...)` returned a valid
`RidePackage`:

```
ride.id        2026-07-13_lohjanharjun-mtb
ride.timezone  Europe/Helsinki
ride.capturedAt 2026-07-13T07:07:07+00:00      (from timeline.start_utc)
track.points   1623                             (of 3438 timeline rows)
track.start    2026-07-13T07:15:13.000Z
video0         VID_20260713_101506_00_009.mp4  3840x2160 hevc 29.97fps
```

`track.points` 1623 < 3438 timeline rows is **correct**: only the Garmin GPS
window (07:15:13–07:42:15, 1623 s) has lat/lon; the reader drops fixless rows
(matches provenance `garmin.gps span_s = 1623`). The clip block round-tripped
into a `VideoAsset` with exact geometry/codec/fps. The reader read the **parquet**
primary (hyparquet resolved from `packages/telemetry/node_modules`).

---

## 5. Findings

### Adopted (this change)

1. **Clip block now travels in ADP** — `adp wrap` emits the schema-reserved
   `role:"clips"` part (`clips.json`, verbatim). Additive; closes the only
   blocking round-trip gap. Logged in `CHANGELOG.md`.

### Parked for morning (not guessed)

> **Update (hardening pass):** findings 1 and 3 are now resolved — see the inline
> notes and `CHANGELOG.md`.

1. **Canonical clips schema.** ~~`clips.json` is emitted verbatim…~~
   **Resolved.** `schemas/clips.schema.json` now defines a sport-neutral canonical
   clip; `wrap` maps rfr's clip block onto it (total mapping, nothing dropped);
   `validate` validates the clips part against it. Decisions taken: the video
   technical fields are generalized under `video.{…}`, and `offset_s` lives **on
   the clip** (per-footage video↔telemetry sync) — *not* on
   `provenance.sources[].clock_sync_offset_s`, which is per-source clock offset.
   The clips part is now **layer 3**. `project` maps the canonical clips back to a
   **byte-identical** v0 `clips[]` (verified against the original rfr manifest for
   every processed ride).
2. **`generated_utc` semantics.** The projected v0 `generated_utc` is the **ADP
   wrap time**, not the producer's original `manifest.generated_utc`
   (`2026-07-14T08:50:10Z`) — ADP-light carries the producer *version* but not the
   producer's manifest timestamp. Harmless here (the LT reader never reads
   `generated_utc`; the value is a valid ISO date-time). Optionally carry the
   producer's original timestamp on the ADP session if faithful provenance of
   *when the producer built its manifest* is wanted. Parked.
3. **`validation.warnings` dropped.** ~~rfr `validation.json` warnings are not
   carried by ADP-light…~~ **Resolved on the ADP side.** The warnings (and the
   sibling cross-source diagnostics) now travel in `provenance.diagnostics`
   (`warnings`, `source_overlap_s`, `hr_mean_abs_diff_bpm`, `video_sync`). The v0
   *projection* still emits an empty `warnings: []` because the LT reader never
   reads that block; a consumer that wants them reads `provenance.diagnostics`
   from the light core.
4. **Ride slug identity.** ADP has no first-class human ride slug; the activity
   is keyed by `session_ref` (UUID). The projection recovers the v0 slug from the
   package directory name. Fine for the local/consumer view; if a stable
   human-facing slug should be a canonical fact, it needs a home on the ADP
   session. Parked.

---

## 6. Reproduce

```
cd D:/MTB/action-data
python -m adp.cli wrap    "D:/MTB/rides/2026-07-13_lohjanharjun-mtb" -o out
python -m adp.cli validate out/2026-07-13_lohjanharjun-mtb
python -m adp.cli project  out/2026-07-13_lohjanharjun-mtb --to ridepackage-v0 --verify
```

Live reader run (optional; requires the already-built LT telemetry dist, no
install/build, no LT changes) — a ~20-line ESM runner importing
`packages/telemetry/dist/index.js` by file URL and calling `readRidePackage` on
the projected folder. Kept outside the read-only live-trails repo.
