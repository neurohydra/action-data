# Changelog

All notable changes to the ADP reference tooling and schemas.

## [Unreleased]

### Added
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
- **No JSON Schema file was modified.** The `clips` part is permitted by the
  existing `manifest.schema.json` (`role` enum already includes `clips`). A
  canonical `clips.schema.json` (which clip fields generalize across sports; where
  the video↔telemetry sync offset lives) is deliberately **not** authored yet —
  parked for review; see `COMPAT_LT.md` §5.
