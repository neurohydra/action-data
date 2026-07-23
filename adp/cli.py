"""adp command-line interface.

Entry point ``adp`` (see ``pyproject.toml`` ``[project.scripts]``).

``wrap``     turns an rfr producer ride folder into an ADP-light package.
``validate`` checks an ADP package (or its manifest) against the canonical
             schemas and re-verifies content hashes.
"""

from __future__ import annotations

import argparse
import sys

from . import ADP_VERSION, __version__
from .validate import validate_package
from .wrap import WrapError, wrap


def _cmd_wrap(args: argparse.Namespace) -> int:
    try:
        pkg_dir = wrap(args.input, args.out)
    except WrapError as e:
        print(f"adp wrap: {e}", file=sys.stderr)
        return 1
    print(f"adp wrap: wrote {pkg_dir}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    ok, checks = validate_package(args.target)
    width = max((len(c.name) for c in checks), default=0)
    for c in checks:
        if c.ok:
            status = "PASS" if not c.soft else "PASS*"
        else:
            status = "FAIL"
        line = f"  [{status:>5}] {c.name:<{width}}"
        if c.detail:
            line += f"  {c.detail}"
        print(line)
    print(f"adp validate: {'OK' if ok else 'FAILED'} "
          f"({sum(1 for c in checks if not c.ok and not c.soft)} hard failure(s))")
    return 0 if ok else 1


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
