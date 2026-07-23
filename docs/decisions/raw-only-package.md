# Decision: raw-only (layer-1-only) ADP package?

**Status: DECIDED 2026-07-24 — NO raw-only package.** Raw data is an *input to
processing*, not a terminal ADP package. `adp wrap` continues to refuse
unprocessed dumps (see Decision at the end). The analysis below is kept for the
record.

## The case that raised it

`D:/MTB/rides/2026-07-22_lohjanharjun-mtb-2` is a captured-but-unrefined ride:
only `ride.yaml` + an ~11 GB DJI `.MP4`. `fit/` is empty; there is **no**
producer `manifest.json` and no `derived/`. With no producer manifest there are
no session aggregates, no canonical 1 Hz timeline, and no provenance — nothing in
layer 2 or 3 to emit. `adp wrap` refuses it with a clear message and exits
non-zero:

```
adp wrap: 2026-07-22_lohjanharjun-mtb-2: no manifest.json — ride is not
processed by the producer (rfr) yet; nothing to wrap.
```

This is an **input-completeness** gap, not a schema gap.

## The option

Define a **raw-only** package: a layer-1-only ADP (the `video` — and any `raw`
— parts in the `heavy` tier, with an empty or near-empty `light` core, no
`session`/`timeline`/`provenance`). It would serve the **pure-backup** use case:
get the originals off the SD card into a portable, hash-addressed, BYOS-locatable
container *before* any refining happens, and refine later without re-importing.

The manifest schema **already permits this shape** structurally: no `session`
part is required, `parts[]` only needs `minItems: 1`, and `tiers.light` may be
empty. So this is a policy/UX decision about what `wrap` should *produce*, not a
schema change.

## Tradeoffs

**For**
- Serves a real need (backup/transfer of raw footage) that the light-core
  packages do not — today those originals travel only inside a fully-refined
  package's `heavy` tier.
- Preserves identity (`session_ref` UUID) and per-source content hashes from the
  moment of capture, so a later refine can attach to the same logical activity
  and dedup detects re-imports.
- No schema work required; the manifest already allows it.

**Against**
- Advertises an "ADP package" that has **no layer-2 core** — the portable,
  scrubbed canonical timeline is the whole point of the format. A consumer that
  fetches a raw-only package's `light` tier gets nothing usable; that is
  potentially misleading.
- Blurs the "facts, scrubbed, egressable" contract: raw layer-1 never egresses
  by policy, so a package whose only content is `heavy` is a backup artifact, not
  a shareable one. It may deserve a distinct marker (e.g. a manifest
  `kind: "raw-backup"` or an explicit empty-`light` contract) rather than
  silently looking like a normal package.
- `wrap` currently keys off the producer manifest for everything (identity,
  timezone, activity hint). A raw-only path needs its own minimal input contract
  (where does `session_ref` come from? timezone? the sidecar `ride.yaml`?), which
  is new surface area.

## Recommendation

**Do not implement yet.** If the pure-backup need is real, the cleaner shape is a
**distinct, clearly-marked** raw-only package (empty `light`, `heavy`-only,
an explicit manifest marker so consumers can tell it apart) rather than emitting
an ordinary-looking package with a hollow core. Keep `wrap`'s current refusal
until the owner decides, so we never quietly produce a coreless package. If
adopted, spec the minimal raw-only input contract (identity + timezone source
from the `ride.yaml` sidecar) and add the manifest marker in the same change.

## Decision (2026-07-24)

**No raw-only package.** The owner decided that raw data is the *input to
processing*, not a terminal package — the whole point of the format is the
processed layer-2 core. If raw footage exists it is sufficient for the first
(capture) phase; it is then processed by the producer into a layer-2 package.
`adp wrap` therefore continues to refuse unprocessed dumps: the path for a raw
DJI clip is *process it first (→ producer manifest + `derived/`), then wrap* —
never *wrap a coreless package*. No schema change; `wrap`'s refusal stays as-is.
