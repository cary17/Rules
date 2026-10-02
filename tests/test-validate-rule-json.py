#!/usr/bin/env python3
"""Tests for the rule-set validator and semantic comparator.

``compare`` decides equivalence with the compiler, so the expectations here were
established by compiling each pair with sing-box: two documents are equivalent
exactly when their rule-set binaries are byte identical. The pairs below are the
counterexamples found while the comparator tried to reproduce compiler
normalisation in Python; they are kept so that the behaviour cannot silently
regress.
"""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate-rule-json.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SING_BOX_AVAILABLE = module._sing_box() is not None


def _compare(left_value, right_value):
    with tempfile.TemporaryDirectory() as tmp:
        left = Path(tmp) / "left.json"
        right = Path(tmp) / "right.json"
        left.write_text(json.dumps(left_value))
        right.write_text(json.dumps(right_value))
        return module.main(["validate-rule-json.py", "compare", str(left), str(right)])


def _document(rule, version=1):
    return {"version": version, "rules": [rule]}


def _needs_compiler(case):
    """Skip cases whose expectation requires sing-box.

    Canonical forms are only known to be equivalent because the compiler says
    so, so those cases cannot be asserted when sing-box is unavailable. The
    workflow runs this file again after downloading sing-box.
    """
    if SING_BOX_AVAILABLE:
        return True
    print(f"SKIP (no sing-box): {case}")
    return False


def test_scalar_and_single_item_array_have_same_semantics():
    if not _needs_compiler("scalar versus one element list"):
        return
    assert _compare(
        _document({"domain_keyword": ["nintendo"]}),
        _document({"domain_keyword": "nintendo"}),
    ) == 0


def test_multiple_items_are_not_collapsed():
    assert _compare(
        _document({"domain": ["a", "b"]}),
        _document({"domain": ["a"]}),
    ) == 1


def test_rejects_invalid_rule_structure_and_matcher_values():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "invalid.json"
        for value in (
            {"version": -1, "rules": [{"domain": ["a"]}]},
            {"version": 1, "rules": [None]},
            {"version": 1, "rules": [{"domain": [None, 123, {}]}]},
        ):
            path.write_text(json.dumps(value))
            try:
                module.load(path)
            except ValueError:
                pass
            else:
                raise AssertionError(value)


def test_compiler_normalised_forms_are_equivalent():
    """These pairs compile to the same rule-set binary."""
    if not _needs_compiler("compiler normalised forms"):
        return
    cases = [
        # scalar versus one element list, across several listable fields
        (_document({"port": [443]}), _document({"port": 443})),
        (_document({"network": ["tcp"]}), _document({"network": "tcp"})),
        (_document({"source_ip_cidr": ["192.0.2.0/24"]}), _document({"source_ip_cidr": "192.0.2.0/24"})),
        (_document({"process_name": ["example"]}), _document({"process_name": "example"})),
        # unordered, deduplicated domain lists
        (_document({"domain": ["z.example", "a.example"]}), _document({"domain": ["a.example", "z.example"]})),
        (_document({"domain": ["a.example", "a.example"]}), _document({"domain": ["a.example"]})),
        # DNS query type numbers and names
        (_document({"query_type": [1]}), _document({"query_type": ["A"]})),
        (_document({"query_type": [28]}), _document({"query_type": ["AAAA"]})),
        (_document({"query_type": [65]}), _document({"query_type": ["HTTPS"]})),
        # CIDR host bits and adjacent networks
        (_document({"ip_cidr": ["192.0.2.1/24"]}), _document({"ip_cidr": ["192.0.2.0/24"]})),
        (_document({"source_ip_cidr": ["192.0.2.0/25", "192.0.2.128/25"]}),
         _document({"source_ip_cidr": ["192.0.2.0/24"]})),
        # logical sub-rule scalar forms and omitted default control fields
        (_document({"type": "logical", "mode": "or", "rules": [{"domain": ["a.example"]}]}),
         _document({"type": "logical", "mode": "or", "rules": [{"domain": "a.example"}]})),
        (_document({"type": "default", "invert": False, "domain": ["a.example"]}),
         _document({"domain": ["a.example"]})),
        # a bare null and an empty list compile to an absent condition
        (_document({"domain": "a.example", "process_name": None}), _document({"domain": "a.example"})),
        (_document({"domain": "a.example", "ip_cidr": []}), _document({"domain": "a.example"})),
    ]
    for left_value, right_value in cases:
        assert _compare(left_value, right_value) == 0, (left_value, right_value)


def test_real_differences_are_detected():
    """These pairs are different rule-sets, including subtle condition changes."""
    cases = [
        # plain value changes
        (_document({"port": [443]}), _document({"port": [80]})),
        (_document({"domain": ["a.example"]}), _document({"domain": ["b.example"]})),
        (_document({"domain_suffix": ["a.example"]}), _document({"domain": ["a.example"]})),
        (_document({"ip_cidr": ["192.0.2.0/24"]}), _document({"ip_cidr": ["192.0.2.0/25"]})),
        (_document({"ip_cidr": ["192.0.2.0/24"]}), _document({"ip_cidr": ["192.0.3.0/24"]})),
        # order sensitive fields: the compiler keeps input order
        (_document({"port": [443, 80]}), _document({"port": [80, 443]})),
        (_document({"network": ["tcp", "udp"]}), _document({"network": ["udp", "tcp"]})),
        (_document({"domain_keyword": ["a", "b"]}), _document({"domain_keyword": ["b", "a"]})),
        # control conditions
        (_document({"domain": ["a.example"], "invert": True}), _document({"domain": ["a.example"]})),
        (_document({"type": "logical", "mode": "or", "rules": [{"domain": ["a.example"]}]}),
         _document({"type": "logical", "mode": "and", "rules": [{"domain": ["a.example"]}]})),
        # a bare null is an absent condition; [null] is not
        (_document({"domain": "a.example", "process_name": None}),
         _document({"domain": "a.example", "process_name": [None]})),
        # an empty interface mapping is not the same as a missing field
        (_document({"network_interface_address": {}}, 4), _document({"domain": "a.example"})),
        # an interface entry holding null differs from an empty mapping
        (_document({"network_interface_address": {"wifi": None}}, 4),
         _document({"network_interface_address": {}}, 4)),
        # a rule with no conditions at all is not a rule with an inert control field
        (_document({"invert": False}), _document({})),
        # boolean must never collapse into an integer
        (_document({"network_is_expensive": True}, 4), _document({"network_is_expensive": 1}, 4)),
    ]
    for left_value, right_value in cases:
        assert _compare(left_value, right_value) == 1, (left_value, right_value)


def test_unknown_query_type_code_is_not_a_name():
    assert _compare(_document({"query_type": [999]}), _document({"query_type": ["A"]})) == 1


def test_uncompilable_document_is_never_reported_equal():
    """A document that fails to compile cannot be confirmed equivalent."""
    assert _compare(_document({"port": [True]}), _document({"port": [1]})) == 1


def test_byte_fallback_is_conservative_without_a_compiler():
    """Without sing-box the fallback only accepts byte identical documents.

    It may report an equivalent pair as a difference, but it can never equate
    two different documents, and it is not fooled by values that Python would
    collapse when parsing.
    """
    original = module._sing_box
    module._sing_box = lambda: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            counter = {"n": 0}

            def write(text):
                counter["n"] += 1
                path = Path(tmp) / f"{counter['n']}.json"
                path.write_text(text)
                return str(path)

            same = json.dumps(_document({"domain": ["a.example"]}))
            assert module.compare(write(same), write(same)) == 0
            # Different text is never reported equal, even when it parses the same.
            assert module.compare(
                write('{"version":1,"rules":[{"domain":["a.example"],"port":1e-400}]}'),
                write('{"version":1,"rules":[{"domain":["a.example"],"port":0.0}]}'),
            ) == 1
            assert module.compare(
                write('{"version":1,"rules":[{"domain":["a.example"],"port":[443]}]}'),
                write('{"version":1,"rules":[{"domain":["a.example"],"port":[80]}]}'),
            ) == 1
            assert module.compare(
                write(json.dumps(_document({"port": [443]}))),
                write(json.dumps(_document({"port": 443}))),
            ) == 1
            # A missing file is a difference, not a crash.
            assert module.compare(str(Path(tmp) / "absent.json"), write(same)) == 1
    finally:
        module._sing_box = original


def test_cli_byte_mode_is_available():
    with tempfile.TemporaryDirectory() as tmp:
        left = Path(tmp) / "left.json"
        right = Path(tmp) / "right.json"
        payload = json.dumps(_document({"port": [443]}))
        left.write_text(payload)
        right.write_text(payload)
        assert module.main(["validate-rule-json.py", "compare-bytes", str(left), str(right)]) == 0
        right.write_text(json.dumps(_document({"port": [80]})))
        assert module.main(["validate-rule-json.py", "compare-bytes", str(left), str(right)]) == 1


def test_compare_requires_the_compiler_for_canonical_forms():
    """Documented trade off: the compiler is what makes canonical forms equal."""
    if not SING_BOX_AVAILABLE:
        print("SKIP: sing-box is not installed")
        return
    assert _compare(_document({"port": [443]}), _document({"port": 443})) == 0
    assert module._sing_box() is not None

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all validation tests passed")
