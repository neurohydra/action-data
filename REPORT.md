# ADP reference tooling — wrap + validate against real ride data

Implemented `adp wrap` and `adp validate` (in `adp/wrap.py`, `adp/validate.py`,
`adp/_util.py`, wired through `adp/cli.py`) and proved them against all five
ride folders in the read-only `D:/MTB/rides` test set. `D:/MTB/rides` was read
only; every artifact was written under `out/` (gitignored).

Environment: Python 3.14, `jsonschema` 4.26. `pandas` 3.0 is present but
`pyarrow` is not, so parquet cannot be read here — the timeline check reads the
CSV fallback via the stdlib `csv` module (every processed ride ships
`derived/timeline.csv`). No dependency had to be installed.

## Headline

| Ride | wrap | validate | notes |
|------|------|----------|-------|
| 2026-07-08_lohja-test | PASS | PASS (0 hard fail) | 2 video segments |
| 2026-07-13_gruotinoja | PASS | PASS (0 hard fail) | |
| 2026-07-13_lohjanharjun-mtb | PASS | PASS (0 hard fail) | |
| 2026-07-20_kalliolle | PASS | PASS (0 hard fail) | no Bosch HR strap -> 19 timeline cols |
| 2026-07-22_lohjanharjun-mtb-2 | REFUSED | n/a | raw DJI dump, not processed (see findings) |

**4 / 5 rides wrap + validate cleanly. The 5th is correctly refused** because it
is a raw camera dump that the producer (rfr) has not processed yet.

## Per-check results (all 4 processed rides)

Every processed ride passed all checks:

- `manifest` — validates against `manifest.schema.json`
- `session` / `provenance` — validate against their schemas
- `session_ref` — the same UUID appears in manifest, session and provenance
- `provenance.raw_hashes` — each `raw_<source>` part hash equals the matching
  `provenance.sources[].hash`
- `timeline.columns` — all 19-20 columns are either canonical or match the
  documented `<source>_raw` / `<source>_<metric>` shadow patterns
- `timeline.time_utc` — present on every sampled row (first, last, 10 seeded-
  random)
- `timeline.rows` — 12 sampled rows validate against `timeline.schema.json`
- `integrity.*` — session, timeline, provenance and both FIT files re-hash to
  the manifest value; video parts carry no hash (soft PASS*, see approximations)
- `tiers` — `light` / `heavy` reference only declared parts

`PASS*` marks a soft pass (informational, never fails the run): the skipped
video hashes and the cross-hash consistency check.

## Light vs heavy byte split

`wrap` produces an **ADP-light** package: the shareable core (session +
timeline + provenance) is materialized/referenced as `light`; the layer-1
originals (FIT + video) are referenced in place as `heavy` and never copied.

| Ride | light | heavy | ratio |
|------|-------|-------|-------|
| 2026-07-08_lohja-test | 220.5 KiB | 33.83 GB | 1 : 149,860 |
| 2026-07-13_gruotinoja | 172.4 KiB | 7.06 GB | 1 : 39,956 |
| 2026-07-13_lohjanharjun-mtb | 206.0 KiB | 21.35 GB | 1 : 101,227 |
| 2026-07-20_kalliolle | 204.0 KiB | 32.26 GB | 1 : 154,400 |

The light core that would egress by default is ~0.2 MB against 7-34 GB of
layer-1 originals — a ~10^5 : 1 reduction. (`light` bytes are the two small
JSON parts plus the referenced ~190 KB parquet timeline; `heavy` is the two
FIT files plus the raw video segments.)

## Schema findings

No schema was strictly *blocked* by the real data, so **no schema change was
made** and there is no `CHANGELOG.md`. Three observations are parked for
morning review:

1. **Unprocessed ride (`2026-07-22_lohjanharjun-mtb-2`).** It has only
   `ride.yaml` + an 11 GB DJI `.MP4`; `fit/` is empty and there is no
   `manifest.json` or `derived/`. This is an **input-completeness** gap, not a
   schema gap: with no producer manifest there are no session aggregates, no
   canonical timeline and no provenance to emit. `wrap` refuses with a clear
   message and exits non-zero. *Question for review:* should ADP define a
   minimal "raw-only" package (video part in `heavy`, empty `light`) for footage
   that has been captured but not yet refined? The manifest schema technically
   permits it (no `session` part is required), but emitting one would advertise
   an ADP package with no layer-2 core, which may be misleading. Not guessed.

2. **Missing per-ride source (`2026-07-20_kalliolle`).** The Bosch unit recorded
   no HR that ride, so there is no `bosch_hr_bpm` column and no `bosch.hr`
   coverage entry. Tooling and schema absorbed this with no change (19 vs 20
   timeline columns, one fewer shadow column, one fewer source-summary metric).
   Recorded only to confirm the open-column design holds under real source
   variation.

3. **Cross-source quality diagnostics have no first-class home.** Producer
   `validation.json` carries `source_overlap_s`, `hr_mean_abs_diff_bpm` and
   `video_sync` — genuine layer-2 provenance-quality facts about clock
   alignment between Garmin and Bosch. `provenance.schema.json` has
   `sources[].dual_hr_anchor` (`against` / `lag_s` / `correlation`), which is
   *close* but semantically about clock lag, not HR agreement. Placing
   `hr_mean_abs_diff_bpm` / `source_overlap_s` is **ambiguous** (own object vs.
   overloading `dual_hr_anchor`, which already allows extra properties), so it
   is parked rather than guessed. These facts are currently dropped by `wrap`.

## Approximations made

- **Video hashes skipped.** Each video part (6-34 GB per file) records `bytes`
  from an actual `stat`, but carries **no content hash** — hashing tens of GB
  per file across the set would stall for many minutes. `part.hash` is optional
  in the manifest schema, so this is schema-valid; `validate` reports these as a
  soft PASS*. FIT files (45-163 KB) and the parquet/CSV timeline are hashed in
  full.
- **`clock_sync_offset_s = 0.0` for both sources.** rfr merges on each device's
  absolute FIT UTC timestamps with no computed re-alignment offset in its
  output, so `0` is the truthful value here, not a placeholder.
- **`scrub.applied = false`.** No scrubbing was performed by this tool, and the
  manifest says so honestly (no home-geofence / precise-start removal was
  implemented for this pass).
- **`refine_version`** is taken from the producer's `pipeline_version`
  (`0.1.0`), the closest available refine/merge version stamp.

## Reproduce

```
cd D:/MTB/action-data
python -m adp.cli wrap "D:/MTB/rides/<ride>" -o out
python -m adp.cli validate out/<ride>
```
