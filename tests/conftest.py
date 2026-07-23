"""Shared pytest fixtures for the ADP reference-tooling test suite.

All tests run against the committed SYNTHETIC fixture under
``tests/fixtures/mini-ride`` — no dependency on ``D:/MTB/rides`` or any
network, so the suite is portable and CI-safe.

The wrap/project working tree is created under a repo-local, gitignored temp
dir (``.adp-test-tmp/``) on purpose: ``adp project`` hardlinks the layer-1
video out of the fixture, and a hardlink only succeeds when source and
destination share a volume. Keeping the working tree on the same volume as the
fixture makes the video-link step succeed on Windows too (on Linux CI any
tmp path works).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
MINI_RIDE = FIXTURES / "mini-ride"
RAW_ONLY = FIXTURES / "raw-only"
SCHEMAS_DIR = REPO_ROOT / "schemas"


@pytest.fixture(scope="session")
def work_dir():
    """A throwaway working directory on the SAME volume as the repo (so video
    hardlinks succeed), cleaned up after the session."""
    base = REPO_ROOT / ".adp-test-tmp"
    base.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="work-", dir=base))
    yield d
    shutil.rmtree(d, ignore_errors=True)
    # remove the base dir if now empty
    try:
        base.rmdir()
    except OSError:
        pass


@pytest.fixture(scope="session")
def wrapped_pkg(work_dir):
    """Wrap the mini-ride fixture into an ADP-light package; return its dir."""
    from adp.wrap import wrap

    return wrap(MINI_RIDE, work_dir / "out")


@pytest.fixture(scope="session")
def projected(wrapped_pkg):
    """Project the wrapped package into a RidePackage v0 folder.

    Returns (out_dir, info). Default target dir is ``<pkg>/ridepackage-v0`` —
    same volume as the wrapped package, so the video link succeeds.
    """
    from adp.project import project_ridepackage_v0

    return project_ridepackage_v0(wrapped_pkg)
