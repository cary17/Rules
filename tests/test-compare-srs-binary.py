#!/usr/bin/env python3
"""Tests for the SRS payload comparison used by the sync fidelity check.

An SRS file is a four byte header followed by a zlib stream. The fidelity check
must accept the same rule-set written with any compression level, and must still
reject a rule-set whose decoded content changed.
"""
import importlib.util
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compare_srs", ROOT / "scripts" / "compare-srs-binary.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

HEADER = b"SRS\x01"
PAYLOAD = b"\x01\x00\x02domain:example.com"


def _write(path, payload, level=6, header=HEADER):
    path.write_bytes(header + zlib.compress(payload, level))
    return str(path)


def test_same_payload_at_any_compression_level_is_equal():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = _write(work / "reference.srs", PAYLOAD, level=6)
        for level in (0, 1, 6, 9):
            other = _write(work / f"level{level}.srs", PAYLOAD, level=level)
            assert module.main(["compare-srs-binary.py", reference, other]) == 0, level


def test_identical_bytes_are_equal():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        first = _write(work / "first.srs", PAYLOAD)
        second = _write(work / "second.srs", PAYLOAD)
        assert module.main(["compare-srs-binary.py", first, second]) == 0


def test_changed_payload_is_detected():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = _write(work / "reference.srs", PAYLOAD)
        changed = _write(work / "changed.srs", PAYLOAD + b"extra")
        assert module.main(["compare-srs-binary.py", reference, changed]) == 1


def test_different_header_is_detected():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = _write(work / "reference.srs", PAYLOAD)
        other_version = _write(work / "v2.srs", PAYLOAD, header=b"SRS\x02")
        assert module.main(["compare-srs-binary.py", reference, other_version]) == 1


def test_undecodable_input_is_reported_as_a_difference():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = _write(work / "reference.srs", PAYLOAD)
        garbage = work / "garbage.srs"
        garbage.write_bytes(b"not-an-srs-file")
        assert module.main(["compare-srs-binary.py", reference, str(garbage)]) == 1
        # A valid file missing entirely must not crash or compare equal.
        assert module.main(["compare-srs-binary.py", reference, str(work / "absent.srs")]) == 1
        # Truncated containers are a difference too.
        truncated = work / "truncated.srs"
        truncated.write_bytes(HEADER)
        assert module.main(["compare-srs-binary.py", reference, str(truncated)]) == 1
        # A stream cut short mid-way must not be accepted either.
        cut = work / "cut.srs"
        cut.write_bytes(HEADER + zlib.compress(PAYLOAD, 6)[:-3])
        assert module.main(["compare-srs-binary.py", reference, str(cut)]) == 1


def test_trailing_junk_is_never_accepted():
    """Data after the zlib stream means the container is not a clean rule-set."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = _write(work / "reference.srs", PAYLOAD)
        for name, body in (
            ("junk", zlib.compress(PAYLOAD, 6) + b"EXTRA"),
            ("two-streams", zlib.compress(PAYLOAD, 6) + zlib.compress(PAYLOAD, 6)),
            ("appended", Path(reference).read_bytes() * 2),
        ):
            candidate = work / f"{name}.srs"
            candidate.write_bytes(HEADER + body)
            assert module.main(["compare-srs-binary.py", reference, str(candidate)]) == 1, name


def test_invalid_magic_is_rejected_even_when_both_sides_match():
    """Two files with the same invalid magic are not a valid rule-set pair."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        first = _write(work / "first.srs", PAYLOAD, level=6, header=b"BAD\x01")
        second = _write(work / "second.srs", PAYLOAD, level=1, header=b"BAD\x01")
        assert module.main(["compare-srs-binary.py", first, second]) == 1
        # A file too short to even hold the header is rejected.
        short = work / "short.srs"
        short.write_bytes(b"SR")
        assert module.main(["compare-srs-binary.py", first, str(short)]) == 1


def test_usage_error():
    assert module.main(["compare-srs-binary.py", "only-one"]) == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all srs comparison tests passed")
