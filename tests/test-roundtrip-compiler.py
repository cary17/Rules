#!/usr/bin/env python3
"""Round-trip fixtures against the real sing-box compiler.

The sync pipeline decompiles an upstream rule-set and then compiles it back, so
every canonical form sing-box produces has to compare equal to the document it
was produced from. Because the comparator itself uses the compiler, these tests
also prove the two agree: each fixture is compiled, decompiled, and the original
and the decompiled document must be reported as equivalent.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts" / "validate-rule-json.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SING_BOX = os.environ.get("SING_BOX_BIN") or shutil.which("sing-box")

FIXTURES = {
    "scalar-domains": {"version": 1, "rules": [{"domain": ["a.example"], "domain_suffix": ["b.example"]}]},
    "unordered-domains": {
        "version": 1,
        "rules": [{"domain": ["z.example", "a.example", "m.example"], "domain_suffix": ["zz.com", "aa.com"]}],
    },
    "duplicate-domains": {
        "version": 1,
        "rules": [{"domain": ["a.example", "a.example", "b.example"], "ip_cidr": ["203.0.113.0/24", "192.0.2.0/24"]}],
    },
    "host-bits-cidr": {"version": 1, "rules": [{"ip_cidr": ["192.0.2.1/24", "2001:db8::1/32"]}]},
    "merged-cidr": {
        "version": 1,
        "rules": [{"source_ip_cidr": ["192.0.2.0/25", "192.0.2.128/25"]}],
    },
    "mixed-ip": {"version": 1, "rules": [{"ip_cidr": ["192.0.2.0/24", "2001:db8::/32"]}]},
    "domain-keyword-and-regex": {
        "version": 1,
        "rules": [{"domain_keyword": ["keyword", "second"], "domain_regex": ["^ads\\.", "^track\\."]}],
    },
    "listable-scalars": {
        "version": 1,
        "rules": [{"port": [443], "network": ["tcp"], "source_ip_cidr": ["192.0.2.0/24"]}],
    },
    "listable-multiple": {
        "version": 1,
        "rules": [{
            "port": [8443, 443, 80],
            "port_range": ["1000:2000", "1:100"],
            "source_port": [443],
            "process_name": ["example", "other"],
            "package_name": ["com.example.app"],
            "wifi_ssid": ["example-net"],
            "wifi_bssid": ["00:00:00:00:00:01"],
        }],
    },
    "query-type-numbers": {"version": 1, "rules": [{"query_type": [1, 28, 65]}]},
    "logical-or": {
        "version": 1,
        "rules": [{
            "type": "logical",
            "mode": "or",
            "rules": [{"domain": ["a.example"]}, {"domain_suffix": ["b.example"]}],
        }],
    },
    "logical-and-mixed": {
        "version": 1,
        "rules": [{
            "type": "logical",
            "mode": "and",
            "rules": [{"domain": ["a.example"], "domain_suffix": ["b.example"]}],
        }],
    },
    "logical-with-listable": {
        "version": 1,
        "rules": [{
            "type": "logical",
            "mode": "and",
            "rules": [{"domain": ["a.example"]}, {"port": [443], "network": ["tcp"]}],
        }],
    },
    "inverted": {"version": 1, "rules": [{"domain": ["a.example"], "invert": True}]},
    "default-control-fields": {
        "version": 1,
        "rules": [{"type": "default", "invert": False, "domain": ["a.example"]}],
    },
    "null-condition": {"version": 1, "rules": [{"domain": "a.example", "process_name": None}]},
    "empty-condition": {"version": 1, "rules": [{"domain": "a.example", "ip_cidr": []}]},
    "interface-address": {
        "version": 4,
        "rules": [{"network_interface_address": {"wifi": ["192.0.2.0/24"], "ethernet": ["198.51.100.0/24"]}}],
    },
    "network-type": {"version": 3, "rules": [{"network_type": ["wifi"], "network_is_expensive": False}]},
    "multiple-rules": {
        "version": 1,
        "rules": [
            {"domain": ["a.example"]},
            {"domain_suffix": ["b.example"], "port": [443]},
            {"ip_cidr": ["192.0.2.0/24"], "invert": True},
        ],
    },
}


def _round_trip(tmp: Path, name: str, document) -> tuple[Path, Path]:
    source = tmp / f"{name}.json"
    compiled = tmp / f"{name}.srs"
    decompiled = tmp / f"{name}.roundtrip.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    subprocess.run(
        [SING_BOX, "rule-set", "compile", str(source), "--output", str(compiled)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [SING_BOX, "rule-set", "decompile", str(compiled), "--output", str(decompiled)],
        check=True, capture_output=True,
    )
    return source, decompiled


def test_every_fixture_survives_the_compiler_round_trip():
    if not SING_BOX:
        print("SKIP: sing-box is not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name, document in FIXTURES.items():
            source, decompiled = _round_trip(work, name, document)
            code = module.main(["validate-rule-json.py", "compare", str(source), str(decompiled)])
            assert code == 0, f"{name} round trip was reported as a semantic mismatch"
        print(f"PASS: {len(FIXTURES)} fixtures survive the compiler round trip")


def test_round_trip_still_detects_a_changed_condition():
    """A dropped or altered condition must never pass the comparison."""
    if not SING_BOX:
        return
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source, decompiled = _round_trip(work, "baseline", {"version": 1, "rules": [{"domain": ["a.example"], "port": [443]}]})
        assert module.main(["validate-rule-json.py", "compare", str(source), str(decompiled)]) == 0

        for name, rule in (
            ("dropped-condition", {"domain": ["a.example"]}),
            ("changed-port", {"domain": ["a.example"], "port": [8443]}),
            ("changed-domain", {"domain": ["b.example"], "port": [443]}),
            ("added-invert", {"domain": ["a.example"], "port": [443], "invert": True}),
        ):
            changed = work / f"{name}.json"
            changed.write_text(json.dumps({"version": 1, "rules": [rule]}), encoding="utf-8")
            assert module.main(["validate-rule-json.py", "compare", str(changed), str(decompiled)]) == 1, name
        print("PASS: round trip comparison still detects changed conditions")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all compiler round-trip tests passed")
