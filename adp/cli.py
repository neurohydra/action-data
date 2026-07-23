"""adp command-line interface.

Entry point ``adp`` (see ``pyproject.toml`` ``[project.scripts]``).

The two subcommands are **placeholders** in this scaffold so the entry point
resolves and the surface is documented; the real implementations land in a
follow-up task. Each currently prints its plan and exits non-zero to make it
unmistakable that nothing was produced.
"""

from __future__ import annotations

import argparse
import sys

from . import ADP_VERSION, __version__

_NOT_IMPLEMENTED = 2


def _cmd_wrap(args: argparse.Namespace) -> int:
    """Wrap producer output into an ADP package (FOLLOW-UP task).

    Planned: read a producer folder (e.g. an rfr ride folder — manifest.json +
    derived/timeline.parquet + video/ + validation.json), emit
    ``adp.manifest.json`` plus the layer-2 parts (session, timeline, geo,
    provenance) and layer-3 clips, resolving each part's location/hash/bytes.
    """
    print(f"adp wrap: not implemented yet (input={args.input!r}, out={args.out!r})")
    print("  Planned: producer folder -> adp.manifest.json + parts[] (session,")
    print("  timeline, geo, provenance, clips), tiers light/heavy.")
    return _NOT_IMPLEMENTED


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate an ADP package (or producer folder) against the schemas
    (FOLLOW-UP task).

    Planned: resolve the manifest, validate every part against its schema in
    ``schemas/``, verify per-source sha256 hashes and per-column coverage.
    """
    print(f"adp validate: not implemented yet (target={args.target!r})")
    print("  Planned: validate manifest + parts against schemas/, check")
    print("  per-source sha256 and provenance.canonical coverage.")
    return _NOT_IMPLEMENTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adp",
        description="Action-data package (ADP) reference tooling.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"adp {__version__} (ADP format {ADP_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_wrap = sub.add_parser("wrap", help="wrap producer output into an ADP package")
    p_wrap.add_argument("input", help="producer folder to wrap (e.g. an rfr ride folder)")
    p_wrap.add_argument("-o", "--out", default="out", help="output directory (default: out/)")
    p_wrap.set_defaults(func=_cmd_wrap)

    p_val = sub.add_parser("validate", help="validate an ADP package against the schemas")
    p_val.add_argument("target", help="package directory / manifest / producer folder")
    p_val.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
