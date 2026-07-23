"""Store-alias resolution for ADP packages.

A manifest's ``parts[].location.store`` carries only a *logical* alias:

* ``default`` — the service's own default store,
* ``cold``    — archival storage (may need rehydration),
* ``byos:<alias>`` — a user-supplied store, named by ``<alias>``.

The manifest deliberately leaks no account, location, or credential. A reader
resolves an alias to a real endpoint using a **storage map** — a SEPARATE,
user-held file (``storage-map.schema.json``) that is NOT part of the package.
Secrets never live inline: a store references its credentials by name only.

Default behavior with no storage map is unchanged: a ``default`` part key is a
local path (absolute as-is, relative under the package dir), exactly as
``adp wrap`` emits today. ``byos:``/``cold`` aliases require a storage map.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ._util import validator


class StoreResolutionError(Exception):
    """Raised when a location's store alias cannot be resolved."""


@dataclass
class Resolved:
    """Result of resolving a part's ``location`` through a storage map.

    ``local_path`` is set only when the store is a local filesystem endpoint;
    for remote stores it is ``None`` and ``uri`` holds a best-effort locator.
    ``available`` is True when the bytes are locally readable right now.
    """

    store: str
    kind: str
    local_path: Path | None = None
    uri: str | None = None
    available: bool = False
    needs_rehydration: bool = False


def parse_store_token(token: str) -> tuple[str, str | None]:
    """Split a store token into (kind, alias). ``default``/``cold`` -> alias
    None; ``byos:<alias>`` -> ("byos", "<alias>")."""
    if token in ("default", "cold"):
        return token, None
    if token.startswith("byos:"):
        alias = token[len("byos:"):]
        if not alias:
            raise StoreResolutionError(f"malformed store token: {token!r}")
        return "byos", alias
    raise StoreResolutionError(f"unknown store token: {token!r}")


def load_storage_map(path: str | Path) -> dict:
    """Load and schema-validate a storage map file."""
    p = Path(path)
    if not p.is_file():
        raise StoreResolutionError(f"storage map not found: {p}")
    try:
        smap = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise StoreResolutionError(f"storage map is not valid JSON: {e}") from e
    errs = sorted(validator("storage-map").iter_errors(smap),
                  key=lambda e: list(e.path))
    if errs:
        loc = "/".join(str(x) for x in errs[0].path) or "<root>"
        raise StoreResolutionError(
            f"storage map fails storage-map.schema at {loc}: {errs[0].message}")
    return smap


def _lookup(smap: dict | None, alias_key: str) -> dict | None:
    if not smap:
        return None
    return smap.get("stores", {}).get(alias_key)


def _join_key(base: str, prefix: str | None, key: str) -> str:
    parts = [base.rstrip("/")]
    if prefix:
        parts.append(prefix.strip("/"))
    parts.append(key.lstrip("/"))
    return "/".join(p for p in parts if p != "")


def resolve_location(location: dict, *, storage_map: dict | None = None,
                     pkg_dir: Path | None = None) -> Resolved:
    """Resolve one manifest ``location`` (``{store, key}``) to a Resolved.

    * ``default`` with no map entry: local — key is used as-is (absolute) or
      under ``pkg_dir`` (relative). This is the historical behavior.
    * any alias present in the storage map: resolved via its entry. A
      ``kind: local`` entry yields a local_path; remote entries yield a uri
      only (not fetchable by this reference tooling).
    * ``byos:``/``cold`` with no map entry: unresolvable -> StoreResolutionError.
    """
    store = location["store"]
    key = location["key"]
    kind_token, alias = parse_store_token(store)

    # alias to look up in the storage map: default/cold by literal name,
    # byos:<alias> by <alias>.
    alias_key = alias if kind_token == "byos" else kind_token
    entry = _lookup(storage_map, alias_key)

    if entry is not None:
        ekind = entry["kind"]
        needs_rehydration = bool(entry.get("cold")) or kind_token == "cold"
        if ekind == "local":
            resolved = _join_key(entry["endpoint"], entry.get("prefix"), key)
            lp = Path(resolved)
            return Resolved(store=store, kind="local", local_path=lp,
                            available=lp.is_file(),
                            needs_rehydration=needs_rehydration)
        uri = _join_key(entry["endpoint"], entry.get("prefix"), key)
        return Resolved(store=store, kind=ekind, uri=uri, available=False,
                        needs_rehydration=needs_rehydration)

    # no storage-map entry
    if kind_token == "default":
        # historical local behavior: key as-is (absolute) or under pkg_dir.
        p = Path(key)
        lp = p if p.is_absolute() else ((pkg_dir / key) if pkg_dir else p)
        return Resolved(store=store, kind="local", local_path=lp,
                        available=lp.is_file())

    raise StoreResolutionError(
        f"store '{store}' has no entry in the storage map "
        f"(looked up '{alias_key}'); provide one via --storage-map")


def resolve_local(location: dict, *, storage_map: dict | None = None,
                  pkg_dir: Path | None = None) -> Path | None:
    """Convenience: the local filesystem path for a location, or None when the
    part lives in a remote store (not locally readable by this tooling)."""
    return resolve_location(location, storage_map=storage_map,
                            pkg_dir=pkg_dir).local_path
