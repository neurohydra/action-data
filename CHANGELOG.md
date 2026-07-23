# Changelog

All notable changes to the ADP reference tooling and schemas.

## [1.0] - 2026-07-24

ADP format **locked to v1** following acceptance of live-trails **ADR-0036**
(ADP = canonical package format, superseding RidePackage v0). `adp_version` is
now `1.0`. Both v1-gating open items were resolved first: raw-only package
decided **NO** (raw is a processing input, not a terminal package — see
`docs/decisions/raw-only-package.md`), and store-alias resolution + canonical
`clips.schema.json` completed (below). RidePackage v0 remains available as a
regenerable consumer projection via `adp project --to ridepackage-v0`.

### Added
- **`schemas/clips.schema.json`** (draft 2020-12) — canonical, sport-neutral
  contract for the `clips` part: an array of first-class clip objects, each
  placing a footage segment on the canonical timeline
  (`start_utc`/`end_utc`/`duration_s`), referencing a video asset (`video_ref`),
  carrying the video↔telemetry sync offset **on the clip** (`offset_s`), the
  generalized video technical block
  (`video.{file,width,height,fps,codec,size_bytes,recording_start_utc}`), and
  optional `direction`/`intent`/`labels`/`description`/`derived_metrics`.
  `adp wrap` now **maps** rfr's `manifest.clips[]` onto this canonical shape (the
  mapping is total — no rfr field is dropped) instead of emitting it verbatim;
  the clips part is now **layer 3** (was pragmatically layer 2). `adp validate`
  validates the clips part against this schema. `adp project` maps the canonical
  clips **back** to a byte-identical v0 `clips[]` (verified against the original
  rfr manifest across all processed rides).
- **`schemas/storage-map.schema.json`** (draft 2020-12) + **`adp/store.py`**
  resolver — store-alias resolution (ADP open question #2). The manifest carries
  only logical aliases (`default`/`cold`/`byos:<alias>`); a separate user-held
  storage map (NOT part of the package) resolves each alias to a real endpoint,
  with credentials referenced by name only — never inline secrets. `adp validate`
  and `adp project` accept an optional `--storage-map`; default local packages
  behave exactly as before when no map is given.
- **`provenance.diagnostics`** block in `provenance.schema.json` — a home for the
  cross-source merge-quality facts from rfr `validation.json`
  (`source_overlap_s`, `hr_mean_abs_diff_bpm`, `video_sync`, `warnings`). These
  are deterministic refine-time facts about merge quality, so they live in
  provenance. `adp wrap` now carries them (present keys only; block omitted when
  none apply). Resolves the parked findings in `REPORT.md` §Schema-findings-3 and
  `COMPAT_LT.md` §5.3.
- `docs/decisions/raw-only-package.md` — decision note on whether ADP should
  define a raw-only (layer-1-only) package for unprocessed dumps. **Pending owner
  decision**; `adp wrap`'s refusal of unprocessed rides is unchanged.
- `adp project --to ridepackage-v0` — projects an ADP package back into the
  live-trails RidePackage v0 folder shape its `packages/telemetry` reader
  ingests (`manifest.json` + `derived/timeline.*` + linked `video/`). A
  consumer-side round-trip proof: the v0 manifest is a regenerable consumer view,
  not a canonical ADP fact. `--verify` checks the projection against the LT v0
  contract. See `COMPAT_LT.md`. (`adp/project.py`)
- `adp wrap` now emits a layer-2 `role:"clips"` part (`clips.json`) carrying the
  producer's per-segment media/timing records **verbatim**. This fills the
  manifest schema's already-reserved `clips` role so the segment block (start /
  offset / geometry / codec / size) travels in the light core, making ADP-light a
  faithful superset of the LT consumer contract. Additive: a new part + a new
  `tiers.light` entry; nothing existing changed.

### Notes
- The `clips` part remains permitted by `manifest.schema.json` (`role` enum
  includes `clips`); it is now additionally validated against the new
  `clips.schema.json`, and its `layer` is `3`.
- The parked canonical-clips question (which clip fields generalize across sports;
  where the video↔telemetry sync offset lives) is now **decided**: fields are
  sport-neutral and `offset_s` lives **on the clip** (per-footage sync), not on
  `provenance.sources[].clock_sync_offset_s` (per-source clock). See
  `COMPAT_LT.md` §5.1.
