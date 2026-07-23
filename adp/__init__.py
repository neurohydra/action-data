"""adp — Action-data package format: canonical schema + reference tooling.

See the top-level README for the 3-layer model, the facts-vs-projections
boundary, BYOS, and packaging tiers. The canonical JSON Schemas live in
``schemas/`` (bundled into the wheel under ``adp/schemas``).
"""

__version__ = "0.1.0"

# The ADP format version encoded in ``adp.manifest.json.adp_version``. This is
# the *format* version and is intentionally decoupled from the package version.
ADP_VERSION = "0.1"
