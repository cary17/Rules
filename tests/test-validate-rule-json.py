#!/usr/bin/env python3
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate-rule-json.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_scalar_and_single_item_array_have_same_semantics():
    with tempfile.TemporaryDirectory() as tmp:
        left = Path(tmp) / "left.json"
        right = Path(tmp) / "right.json"
        left.write_text(json.dumps({"version": 1, "rules": [{"domain_keyword": ["nintendo"]}]}))
        right.write_text(json.dumps({"version": 1, "rules": [{"domain_keyword": "nintendo"}]}))
        assert module.main(["validate", "compare", str(left), str(right)]) == 0


def test_multiple_items_are_not_collapsed():
    with tempfile.TemporaryDirectory() as tmp:
        left = Path(tmp) / "left.json"
        right = Path(tmp) / "right.json"
        left.write_text(json.dumps({"version": 1, "rules": [{"domain": ["a", "b"]}]}))
        right.write_text(json.dumps({"version": 1, "rules": [{"domain": ["a"]}]}))
        assert module.main(["validate", "compare", str(left), str(right)]) == 1


if __name__ == "__main__":
    test_scalar_and_single_item_array_have_same_semantics()
    test_multiple_items_are_not_collapsed()
    print("all validation tests passed")
