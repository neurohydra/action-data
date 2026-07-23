"""Clips part contract (clips.schema.json) — the array of canonical clip
objects."""

from __future__ import annotations

from adp._util import validator


def _errors(doc):
    return list(validator("clips").iter_errors(doc))


def _good_clip(**over):
    clip = {
        "video_ref": "video",
        "start_utc": "2026-07-08T06:00:00+00:00",
        "end_utc": "2026-07-08T06:00:05+00:00",
        "duration_s": 5.0,
        "offset_s": 0.0,
        "start_local": "2026-07-08T09:00:00+03:00",
        "direction": "forward",
        "video": {
            "file": "clip.mp4",
            "width": 3840,
            "height": 2160,
            "fps": 29.97,
            "codec": "hevc",
            "size_bytes": 1048576,
            "recording_start_utc": "2026-07-08T06:00:00+00:00",
        },
    }
    clip.update(over)
    return clip


def test_wellformed_clip_validates():
    assert _errors([_good_clip()]) == []


def test_minimal_required_clip_validates():
    minimal = {
        "video_ref": "video",
        "start_utc": "2026-07-08T06:00:00+00:00",
        "end_utc": "2026-07-08T06:00:05+00:00",
        "duration_s": 5.0,
        "offset_s": 0.0,
    }
    assert _errors([minimal]) == []


def test_missing_offset_s_fails():
    clip = _good_clip()
    del clip["offset_s"]
    errs = _errors([clip])
    assert errs, "a clip without offset_s must fail"
    assert any("offset_s" in str(e.message) for e in errs)


def test_bad_direction_fails():
    errs = _errors([_good_clip(direction="sideways")])
    assert errs, "direction must be one of forward/reverse"


def test_zero_duration_fails():
    # duration_s has exclusiveMinimum 0
    errs = _errors([_good_clip(duration_s=0)])
    assert errs, "duration_s must be > 0"


def test_unknown_field_rejected():
    # clip objects are additionalProperties:false
    errs = _errors([_good_clip(bogus="x")])
    assert errs, "unknown clip fields must be rejected"
