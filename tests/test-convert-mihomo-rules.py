#!/usr/bin/env python3
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "convert-mihomo-rules.py"
spec = importlib.util.spec_from_file_location("convert_mihomo_rules", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_domain_behavior_mapping():
    source = {
        "version": 1,
        "rules": [
            {
                "domain": ["example.com"],
                "domain_suffix": ["example.org", ".xbox"],
                "domain_wildcard": ["*.wild.example"],
                "domain_keyword": ["keyword"],
                "domain_regex": [r"^ads\."],
            }
        ],
    }
    lines, skipped = module._render_trie(module._rule_values(source), "domain")
    assert "example.com" in lines
    assert "+.example.org" in lines
    assert "+.xbox" in lines  # leading dot normalized
    assert "+..xbox" not in lines
    assert "*.wild.example" in lines
    assert skipped == {"domain_keyword": 1, "domain_regex": 1}
    assert "keyword" not in lines
    assert "^ads" not in lines


def test_domain_suffix_bare_dot_is_skipped():
    source = {"version": 1, "rules": [{"domain_suffix": ["."]}]}
    lines, skipped = module._render_trie(module._rule_values(source), "domain")
    assert lines == []
    assert skipped == {"domain_suffix": 1}


def test_ipcidr_behavior_mapping():
    source = {
        "version": 1,
        "rules": [
            {"ip_cidr": ["192.0.2.0/24", "2001:db8::/32"], "geoip": ["CN"], "asn": ["12345"]}
        ],
    }
    lines, skipped = module._render_trie(module._rule_values(source), "ipcidr")
    assert "192.0.2.0/24" in lines
    assert "2001:db8::/32" in lines
    assert skipped == {"geoip": 1, "asn": 1}


def test_render_yaml_wraps_payload():
    yaml = module._render_yaml(["+.0x0.st", "example.com"])
    assert yaml == "payload:\n    - +.0x0.st\n    - example.com\n"


def test_convert_directory_outputs_list_and_yaml():
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        output_dir = Path(tmp) / "output"
        source_dir.mkdir()
        (source_dir / "geosite-google.json").write_text(
            json.dumps({"version": 1, "rules": [{"domain_suffix": ["google.com"]}]}),
            encoding="utf-8",
        )
        (source_dir / "geoip-cn.json").write_text(
            json.dumps({"version": 1, "rules": [{"ip_cidr": ["1.0.1.0/24"]}]}),
            encoding="utf-8",
        )
        result = module.convert_directory(source_dir, output_dir, "domain")
        assert result.successful == 1
        assert (output_dir / "google.list").is_file()
        assert (output_dir / "google.yaml").is_file()
        assert (output_dir / "google.list").read_text(encoding="utf-8") == "+.google.com\n"
        # geoip-cn.json must not be converted by the domain pass
        assert not (output_dir / "cn.list").exists()


def test_convert_directory_drops_file_with_only_skipped_rules():
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        output_dir = Path(tmp) / "output"
        source_dir.mkdir()
        (source_dir / "geosite-scholar.json").write_text(
            json.dumps({"version": 1, "rules": [{"domain_keyword": ["scholar"]}]}),
            encoding="utf-8",
        )
        result = module.convert_directory(source_dir, output_dir, "domain")
        assert result.successful == 0
        assert result.skipped == 1
        assert not (output_dir / "scholar.list").exists()
        assert not (output_dir / "scholar.yaml").exists()


if __name__ == "__main__":
    test_domain_behavior_mapping()
    test_domain_suffix_bare_dot_is_skipped()
    test_ipcidr_behavior_mapping()
    test_render_yaml_wraps_payload()
    test_convert_directory_outputs_list_and_yaml()
    test_convert_directory_drops_file_with_only_skipped_rules()
    print("all mihomo conversion tests passed")
