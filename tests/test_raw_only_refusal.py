"""``adp wrap`` refuses an unprocessed (raw-only) folder: no manifest.json /
derived/, so there is nothing to wrap. It fails with a clear error and a
non-zero CLI exit."""

from __future__ import annotations

import pytest

from adp.cli import main
from adp.wrap import WrapError, wrap

from conftest import RAW_ONLY


def test_wrap_refuses_raw_only_folder():
    with pytest.raises(WrapError) as ei:
        wrap(RAW_ONLY)
    msg = str(ei.value).lower()
    assert "manifest.json" in msg or "not processed" in msg


def test_cli_wrap_raw_only_nonzero_exit(capsys):
    rc = main(["wrap", str(RAW_ONLY)])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "adp wrap" in err


def test_wrap_rejects_missing_directory(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(WrapError):
        wrap(missing)
