#!/usr/bin/env python3
"""Rule-set JSON validator and semantic comparator.

``compare`` decides equivalence with the compiler itself: both documents are
compiled with sing-box and the resulting rule-set binaries are compared byte for
byte. No canonicalisation is performed in Python, because that is exactly where
hand written rules kept hiding real differences. Equal binaries prove the two
documents are the same rule-set; every form sing-box normalises internally
(scalar versus one element list, CIDR merging, query type names, unordered
domain lists, default control fields) is therefore handled for free.

The comparison is deliberately conservative. A pair that differs only in a
textual form the compiler keeps verbatim, such as ``192.0.2.1/24`` against
``192.0.2.0/24`` in an interface address field, is reported as a difference. A
false difference skips publishing a rule and is visible in the job summary,
while a false match would silently publish a rule-set that no longer matches
what upstream produced, so the trade off is one sided.

When no sing-box binary is available the comparison degrades to a byte
comparison: two documents are equal only when their files are byte identical, so
the weaker mode can never equate two different rule-sets either.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MATCHER_KEYS = {
    "domain", "domain_suffix", "domain_keyword", "domain_regex",
    "domain_wildcard", "geoip", "ip_cidr", "ip_cidr6", "asn",
}


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value is not an object")
    version = value.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise ValueError("version must be a positive integer")
    rules = value.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a non-empty array")
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"rules[{index}] must be an object")
        for key, item in rule.items():
            if key in MATCHER_KEYS:
                items = item if isinstance(item, list) else [item]
                if any(not isinstance(value, str) for value in items):
                    raise ValueError(f"rules[{index}].{key} must contain only strings")
    if Path(path).stat().st_size == 0:
        raise ValueError("JSON file is empty")
    return value


def _sing_box():
    """Path to the sing-box binary, or None when it is not available."""
    candidate = os.environ.get("SING_BOX_BIN") or "sing-box"
    if os.sep in candidate:
        return candidate if os.access(candidate, os.X_OK) else None
    return shutil.which(candidate)


def _compiled_digest(path, sing_box):
    """SHA-256 of the compiled rule-set, or None when the document cannot compile."""
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "out.srs"
        try:
            process = subprocess.run(
                [sing_box, "rule-set", "compile", str(path), "--output", str(output)],
                capture_output=True,
            )
        except OSError:
            return None
        if process.returncode != 0 or not output.is_file():
            return None
        return hashlib.sha256(output.read_bytes()).hexdigest()


def _byte_compare(left_path, right_path):
    """Compare the files byte for byte, without parsing them.

    Parsing would not be conservative: Python collapses ``1e-400`` and ``0.0``
    into the same float, and ``json.load`` silently keeps only the last of a
    duplicated key, so a parsed comparison can report two different documents as
    equal. Comparing the bytes cannot do that. Reformatting of equivalent JSON is
    reported as a difference, which is the safe direction for this fallback.
    """
    try:
        left = Path(left_path).read_bytes()
        right = Path(right_path).read_bytes()
    except OSError:
        return 1
    return 0 if left == right else 1


def compare(left_path, right_path):
    """Return 0 only when both documents are the same rule-set."""
    sing_box = _sing_box()
    if sing_box:
        left = _compiled_digest(left_path, sing_box)
        right = _compiled_digest(right_path, sing_box)
        if left is None or right is None:
            # A document that does not compile cannot be confirmed equivalent.
            return 1
        return 0 if left == right else 1
    return _byte_compare(left_path, right_path)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "validate":
        load(argv[2])
        return 0
    if len(argv) == 4 and argv[1] == "compare":
        if compare(argv[2], argv[3]) != 0:
            print("JSON semantic mismatch", file=sys.stderr)
            return 1
        return 0
    if len(argv) == 4 and argv[1] == "compare-bytes":
        # Force the compiler independent comparison: byte equality only.
        if _byte_compare(argv[2], argv[3]) != 0:
            print("byte mismatch", file=sys.stderr)
            return 1
        return 0
    print(f"usage: {argv[0]} validate|compare|compare-bytes ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
