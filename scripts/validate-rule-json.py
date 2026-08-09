#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def load(path: str):
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value is not an object")
    version = value.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("version must be an integer")
    rules = value.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a non-empty array")
    if Path(path).stat().st_size == 0:
        raise ValueError("JSON file is empty")
    return value


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "validate":
        load(argv[2])
        return 0
    if len(argv) == 4 and argv[1] == "compare":
        left = load(argv[2])
        right = load(argv[3])
        if left != right:
            print("JSON semantic mismatch", file=sys.stderr)
            return 1
        return 0
    print(f"usage: {argv[0]} validate|compare ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
