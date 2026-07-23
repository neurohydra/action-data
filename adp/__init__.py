"""adp — Action-data package format: canonical schema + reference tooling.

See the top-level README for the 3-layer model, the facts-vs-projections
boundary, BYOS, and packaging tiers. The canonical JSON Schemas live in
``schemas/`` (bundled into the wheel under ``adp/schemas``).
"""

__version__ = "1.0.0"

# The ADP format version encoded in ``adp.manifest.json.adp_version``. This is
# the *format* version and is intentionally decoupled from the package version.
# Locked to 1.0 by live-trails ADR-0036 (accepted 2026-07-24).
ADP_VERSION = "1.0"
