#!/usr/bin/env python3
"""Compare two sing-box rule-set binaries by content instead of container bytes.

An SRS file is a four byte header (``SRS`` plus a format version) followed by a
zlib stream. The same rule-set can therefore be encoded as different files when
the writer picks another compression level, which is why a plain byte comparison
is too strict for the fidelity check: recompiling an upstream artifact can change
the compressed bytes while the rule-set itself is unchanged.

This tool compares the header and the *decompressed* payload, so it answers the
question the sync pipeline actually asks: does the recompiled rule-set still
contain exactly what upstream published?

Exit codes:
  0  same header and same decompressed payload
  1  different, or either input is not a complete, valid rule-set

Anything uncertain is reported as a difference. A rule that cannot be shown to
match upstream is not published, so the reader is deliberately strict: the magic
must be present, the zlib stream must terminate, and no trailing bytes may follow
it. Otherwise a container with appended junk would compare equal to a clean one
and be published.
"""
import sys
import zlib
from pathlib import Path

MAGIC = b"SRS"
HEADER_SIZE = 4


def read_payload(path):
    """Return (header, decompressed payload), or None when not exactly valid."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if len(raw) < HEADER_SIZE or not raw.startswith(MAGIC):
        return None
    header = raw[:HEADER_SIZE]
    decompressor = zlib.decompressobj()
    try:
        payload = decompressor.decompress(raw[HEADER_SIZE:])
        payload += decompressor.flush()
    except zlib.error:
        return None
    # A truncated stream leaves eof unset, and any bytes after the stream ends
    # are unexplained. Both are rejected so only a complete, single stream is
    # ever accepted.
    if not decompressor.eof:
        return None
    if decompressor.unused_data or decompressor.unconsumed_tail:
        return None
    return header, payload


def main(argv):
    if len(argv) != 3:
        print(f"usage: {argv[0]} LEFT.srs RIGHT.srs", file=sys.stderr)
        return 2
    left = read_payload(argv[1])
    right = read_payload(argv[2])
    if left is None or right is None:
        print("rule-set binary could not be decoded for comparison", file=sys.stderr)
        return 1
    if left != right:
        limit = min(len(left[1]), len(right[1]))
        offset = next((index for index in range(limit) if left[1][index] != right[1][index]), limit)
        print(f"rule-set payload differs at offset {offset}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
