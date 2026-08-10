#!/usr/bin/env python3
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "convert-geosite-rules.py"
spec = importlib.util.spec_from_file_location("convert_geosite_rules", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_egern_uses_rule_set_fields_without_policy():
    source = {
        "version": 1,
        "rules": [
            {
                "domain": ["example.com"],
                "domain_suffix": ["example.org"],
                "domain_regex": [r"^ads?\\."],
            }
        ],
    }
    rendered, skipped = module.render_egern(source)
    assert "no_resolve: true" not in rendered
    assert "domain_set:" in rendered
    assert "domain_suffix_set:" in rendered
    assert "domain_regex_set:" in rendered
    assert "policy" not in rendered
    assert skipped == []
    assert "# NAME:" in rendered
    assert "# UPDATED:" in rendered
    assert "# TOTAL:" in rendered
    assert "规则名称" not in rendered


def test_surge_and_loon_skip_unsupported_domain_regex():
    source = {
        "version": 1,
        "rules": [{"domain": ["example.com"], "domain_regex": [r"^ads?\\."]}],
    }
    for renderer in (module.render_surge, module.render_loon):
        rendered, skipped = renderer(source)
        assert "DOMAIN,example.com" in rendered
        assert "DOMAIN-REGEX," not in rendered
        assert "# DOMAIN-REGEX: 1" in rendered
        assert skipped == [("domain_regex", 1)]
        assert "policy" not in rendered.lower()


def test_egern_adds_no_resolve_only_for_ip_rules():
    source = {"version": 1, "rules": [{"ip_cidr": ["192.0.2.0/24"]}]}
    rendered, skipped = module.render_egern(source)
    assert "no_resolve: true" in rendered
    assert "ip_cidr_set:" in rendered
    assert skipped == []


def test_client_with_only_unsupported_regex_has_no_publishable_output():
    source = {
        "version": 1,
        "rules": [{"domain_regex": r"^.+-mihayo\\.akamaized\\.net$"}],
    }
    for renderer in (module.render_surge, module.render_loon):
        rendered, skipped = renderer(source, "mihoyo@cn")
        assert rendered == ""
        assert skipped == [("domain_regex", 1)]


def test_convert_directory_preserves_pairs_and_writes_summary():
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        output_dir = Path(tmp) / "output"
        source_dir.mkdir()
        (source_dir / "geosite-google.json").write_text(
            json.dumps({"version": 1, "rules": [{"domain": ["example.com"]}]}),
            encoding="utf-8",
        )
        result = module.convert_directory(source_dir, output_dir, "egern")
        assert result.successful == 1
        assert result.skipped == 0
        assert (output_dir / "google.yaml").is_file()
        assert not list(output_dir.glob("*.json"))


def test_convert_directory_skips_only_empty_client_file():
    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / "source"
        output_dir = Path(tmp) / "output"
        source_dir.mkdir()
        (source_dir / "geosite-mihoyo@cn.json").write_text(
            json.dumps({"version": 1, "rules": [{"domain_regex": "^mihoyo$"}]}),
            encoding="utf-8",
        )
        (source_dir / "geosite-mihoyo-cn.json").write_text(
            json.dumps({"version": 1, "rules": [{"domain_suffix": ["mihoyo.com"]}]}),
            encoding="utf-8",
        )
        result = module.convert_directory(source_dir, output_dir, "loon")
        assert result.successful == 1
        assert result.skipped == 1
        assert not (output_dir / "mihoyo@cn.list").exists()
        assert (output_dir / "mihoyo-cn.list").is_file()


if __name__ == "__main__":
    test_egern_uses_rule_set_fields_without_policy()
    test_surge_and_loon_skip_unsupported_domain_regex()
    test_convert_directory_preserves_pairs_and_writes_summary()
    print("all conversion tests passed")
