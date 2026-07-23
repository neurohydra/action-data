"""End-to-end round-trip on the mini-ride fixture:
``wrap`` -> ``validate`` (all PASS, 0 hard failures) -> ``project`` -> contract MATCH.
"""

from __future__ import annotations

import json

from adp.project import verify_ridepackage_v0
from adp.validate import validate_package

from conftest import MINI_RIDE


def _csv_data_rows(path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return len(lines) - 1  # minus header


def test_validate_all_checks_pass(wrapped_pkg):
    ok, checks = validate_package(wrapped_pkg)
    hard_failures = [c for c in checks if not c.ok and not c.soft]
    assert hard_failures == [], (
        "hard failures: " + ", ".join(f"{c.name}: {c.detail}" for c in hard_failures)
    )
    assert ok is True
    # every non-soft check is a PASS
    assert all(c.ok for c in checks if not c.soft)


def test_projected_clips_byte_identical_to_fixture(projected):
    out_dir, _info = projected
    fixture_clips = json.loads((MINI_RIDE / "manifest.json").read_text("utf-8"))["clips"]
    projected_clips = json.loads((out_dir / "manifest.json").read_text("utf-8"))["clips"]
    # byte-identical: same fields, same order, same values
    assert json.dumps(projected_clips) == json.dumps(fixture_clips)


def test_projected_timeline_rows_match_csv(projected):
    out_dir, info = projected
    expected = _csv_data_rows(MINI_RIDE / "derived" / "timeline.csv")
    assert expected == 6
    v0 = json.loads((out_dir / "manifest.json").read_text("utf-8"))
    assert v0["timeline"]["rows"] == expected
    assert info["timeline_rows"] == expected


def test_contract_verifier_reports_match(projected):
    out_dir, _info = projected
    ok, checks = verify_ridepackage_v0(out_dir)
    failures = [f"{c.name}: {c.detail}" for c in checks if not c.ok]
    assert ok is True, "contract failures: " + ", ".join(failures)
