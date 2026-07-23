"""adp command-line interface.

Entry point ``adp`` (see ``pyproject.toml`` ``[project.scripts]``).

``wrap``     turns an rfr producer ride folder into an ADP-light package.
``validate`` checks an ADP package (or its manifest) against the canonical
             schemas and re-verifies content hashes.
``project``  projects an ADP package back into a consumer view (e.g. the
             live-trails RidePackage v0 folder) and can verify the result
             against that consumer's contract.
"""

from __future__ import annotations

import argparse
import sys

from . import ADP_VERSION, __version__
from .project import (
    TARGETS,
    ProjectError,
    project_ridepackage_v0,
    verify_ridepackage_v0,
)
from .store import StoreResolutionError, load_storage_map
from .validate import validate_package
from .wrap import WrapError, wrap


def _load_map(path):
    if not path:
        return None
    return load_storage_map(path)


def _cmd_wrap(args: argparse.Namespace) -> int:
    try:
        pkg_dir = wrap(args.input, args.out)
    except WrapError as e:
        print(f"adp wrap: {e}", file=sys.stderr)
        return 1
    print(f"adp wrap: wrote {pkg_dir}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        smap = _load_map(getattr(args, "storage_map", None))
    except StoreResolutionError as e:
        print(f"adp validate: {e}", file=sys.stderr)
        return 2
    ok, checks = validate_package(args.target, storage_map=smap)
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


def _cmd_project(args: argparse.Namespace) -> int:
    if args.to not in TARGETS:
        print(f"adp project: unknown target '{args.to}' (known: {', '.join(TARGETS)})",
              file=sys.stderr)
        return 2
    try:
        smap = _load_map(getattr(args, "storage_map", None))
        out_dir, info = project_ridepackage_v0(args.pkg, args.out, args.ride,
                                               storage_map=smap)
    except (ProjectError, StoreResolutionError) as e:
        print(f"adp project: {e}", file=sys.stderr)
        return 1
    print(f"adp project: wrote {out_dir}")
    print(f"  ride           {info['ride']}")
    print(f"  timeline       {info['timeline_file']}  ({info['timeline_rows']} rows)")
    for v in info["video"]:
        print(f"  video          {v['file']}  [{v['method']}]")
    for note in info["notes"]:
        print(f"  note           {note}")

    if args.verify:
        ok, checks = verify_ridepackage_v0(out_dir)
        width = max((len(c.name) for c in checks), default=0)
        print("  --- LT RidePackage v0 contract ---")
        for c in checks:
            status = "PASS" if c.ok else "FAIL"
            line = f"  [{status:>4}] {c.name:<{width}}"
            if c.detail:
                line += f"  {c.detail}"
            print(line)
        n_fail = sum(1 for c in checks if not c.ok)
        print(f"  contract: {'MATCH' if ok else 'MISMATCH'} ({n_fail} failure(s))")
        if not ok:
            return 1
    return 0


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
    p_val.add_argument("--storage-map", default=None,
                       help="storage map JSON resolving byos:/cold store aliases "
                            "to endpoints (storage-map.schema.json)")
    p_val.set_defaults(func=_cmd_validate)

    p_proj = sub.add_parser(
        "project",
        help="project an ADP package into a consumer view (e.g. ridepackage-v0)",
    )
    p_proj.add_argument("pkg", help="ADP package directory (contains adp.manifest.json)")
    p_proj.add_argument("--to", default="ridepackage-v0",
                        help=f"projection target (default: ridepackage-v0; known: {', '.join(TARGETS)})")
    p_proj.add_argument("-o", "--out", default=None,
                        help="output directory (default: <pkg>/ridepackage-v0)")
    p_proj.add_argument("--ride", default=None,
                        help="override the v0 ride slug (default: package dir name)")
    p_proj.add_argument("--verify", action="store_true",
                        help="verify the projected folder against the LT v0 contract")
    p_proj.add_argument("--storage-map", default=None,
                        help="storage map JSON resolving byos:/cold store aliases "
                             "to local endpoints (storage-map.schema.json)")
    p_proj.set_defaults(func=_cmd_project)

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
