"""Store-alias resolver (adp/store.py) + storage-map contract.

- ``default`` with no map -> local path, unchanged.
- ``byos:<alias>`` fails without a storage map, resolves with one.
- credentials are referenced by NAME only (``credentials_ref``); inline secrets
  are structurally impossible (store is additionalProperties:false).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adp import store
from adp._util import validator


# ── default (no map) ──────────────────────────────────────────────────────────

def test_default_absolute_key_unchanged(tmp_path):
    target = tmp_path / "session.json"
    target.write_text("{}", encoding="utf-8")
    loc = {"store": "default", "key": str(target)}
    resolved = store.resolve_location(loc)
    assert resolved.kind == "local"
    assert resolved.local_path == Path(str(target))
    assert resolved.available is True


def test_default_relative_key_under_pkg_dir(tmp_path):
    loc = {"store": "default", "key": "session.json"}
    resolved = store.resolve_location(loc, pkg_dir=tmp_path)
    assert resolved.local_path == tmp_path / "session.json"


def test_resolve_local_convenience_returns_path(tmp_path):
    loc = {"store": "default", "key": "x.json"}
    assert store.resolve_local(loc, pkg_dir=tmp_path) == tmp_path / "x.json"


# ── byos ──────────────────────────────────────────────────────────────────────

def test_byos_without_map_is_unresolvable():
    loc = {"store": "byos:mybucket", "key": "session.json"}
    with pytest.raises(store.StoreResolutionError):
        store.resolve_location(loc)


def test_byos_with_local_map_resolves(tmp_path):
    base = tmp_path / "store-root"
    base.mkdir()
    (base / "session.json").write_text("{}", encoding="utf-8")
    smap = {
        "version": "1.0",
        "stores": {
            "mybucket": {"kind": "local", "endpoint": str(base)},
        },
    }
    loc = {"store": "byos:mybucket", "key": "session.json"}
    resolved = store.resolve_location(loc, storage_map=smap)
    assert resolved.kind == "local"
    assert resolved.local_path == Path(store._join_key(str(base), None, "session.json"))
    assert resolved.available is True


def test_byos_with_prefix(tmp_path):
    smap = {
        "version": "1.0",
        "stores": {
            "mybucket": {"kind": "local", "endpoint": str(tmp_path), "prefix": "rides/2026"},
        },
    }
    loc = {"store": "byos:mybucket", "key": "session.json"}
    resolved = store.resolve_location(loc, storage_map=smap)
    assert resolved.local_path.as_posix().endswith("rides/2026/session.json")


# ── remote stores + credential handling ───────────────────────────────────────

def test_remote_store_yields_uri_not_local(tmp_path):
    smap = {
        "version": "1.0",
        "stores": {
            "cloud": {
                "kind": "s3",
                "endpoint": "s3://my-bucket",
                "region": "eu-north-1",
                "credentials_ref": "AWS_PROFILE_ACTIONVIDEOS",
            }
        },
    }
    loc = {"store": "byos:cloud", "key": "session.json"}
    resolved = store.resolve_location(loc, storage_map=smap)
    assert resolved.kind == "s3"
    assert resolved.local_path is None
    assert resolved.available is False
    assert resolved.uri == "s3://my-bucket/session.json"


def test_credentials_referenced_by_name_only(tmp_path):
    # a valid map: the secret is a NAME/handle, resolved out of band
    smap = {
        "version": "1.0",
        "stores": {
            "cloud": {
                "kind": "r2",
                "endpoint": "https://acct.r2.cloudflarestorage.com/bucket",
                "credentials_ref": "R2_TOKEN_ENV",
            }
        },
    }
    path = tmp_path / "map.json"
    path.write_text(json.dumps(smap), encoding="utf-8")
    loaded = store.load_storage_map(path)  # schema-validates
    entry = loaded["stores"]["cloud"]
    assert entry["credentials_ref"] == "R2_TOKEN_ENV"
    # the ref is just a name, not a secret value
    assert "://" not in entry["credentials_ref"]


def test_inline_secret_is_rejected_by_schema():
    # store is additionalProperties:false, so an inline secret field cannot exist
    bad = {
        "version": "1.0",
        "stores": {
            "cloud": {
                "kind": "s3",
                "endpoint": "s3://my-bucket",
                "secret_access_key": "AKIA_INLINE_SECRET",
            }
        },
    }
    errs = list(validator("storage-map").iter_errors(bad))
    assert errs, "an inline secret field must be rejected by storage-map.schema"


def test_malformed_byos_token_errors():
    with pytest.raises(store.StoreResolutionError):
        store.parse_store_token("byos:")
