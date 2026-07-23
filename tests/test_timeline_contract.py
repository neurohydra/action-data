"""Timeline row/column contract (timeline.schema.json)."""

from __future__ import annotations

from adp._util import validator
from adp.validate import _SHADOW_RE


def _errors(row):
    return list(validator("timeline").iter_errors(row))


def test_row_missing_time_utc_fails():
    row = {"lat": 60.18, "lon": 24.9}
    errs = _errors(row)
    assert errs, "a row without time_utc must fail validation"
    assert any("time_utc" in str(e.message) for e in errs)


def test_minimal_row_only_time_utc_passes():
    assert _errors({"time_utc": "2026-07-08T06:00:00+00:00"}) == []


def test_nullable_latlon_rows_pass():
    # explicit nulls
    assert _errors({"time_utc": "2026-07-08T06:00:00+00:00",
                    "lat": None, "lon": None}) == []
    # real fixes
    assert _errors({"time_utc": "2026-07-08T06:00:00+00:00",
                    "lat": 60.18, "lon": 24.9}) == []


def test_shadow_and_raw_columns_validate():
    row = {
        "time_utc": "2026-07-08T06:00:00+00:00",
        "bosch_hr_bpm": 137,       # <source>_<metric>
        "bosch_lat": 60.1801,      # <source>_<lat|lon>
        "bosch_lon": 24.9001,
        "garmin_raw": True,        # <source>_raw
        "bosch_raw": None,         # nullable raw flag
    }
    assert _errors(row) == []


def test_shadow_column_names_match_documented_patterns():
    for col in ("bosch_hr_bpm", "garmin_alt_m", "bosch_speed_ms"):
        assert _SHADOW_RE.match(col), f"{col} should match <source>_<metric>"
    for col in ("bosch_lat", "bosch_lon"):
        assert _SHADOW_RE.match(col), f"{col} should match <source>_<lat|lon>"
    for col in ("garmin_raw", "bosch_raw"):
        assert _SHADOW_RE.match(col), f"{col} should match <source>_raw"


def test_out_of_range_latitude_fails():
    errs = _errors({"time_utc": "2026-07-08T06:00:00+00:00", "lat": 120.0})
    assert errs, "latitude above 90 must fail the range constraint"
