#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "optimize-rule-json.py"
spec = importlib.util.spec_from_file_location("optimize_rule_json", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

GOOGLE_GROUP = [
    "google.co.ao", "google.co.bw", "google.co.ck", "google.co.cr",
    "google.co.id", "google.co.il", "google.co.in", "google.co.jp",
]


def test_topic_boundary_comes_from_each_rule_set_filename():
    source = {
        "version": 1,
        "rules": [{"domain_suffix": list(GOOGLE_GROUP)}],
        "source": "geosite-google.json",
    }
    optimized, changes = module.optimize(source, lossy_keywords=True)
    assert optimized["rules"][0]["domain_keyword"] == ["google"]
    assert optimized["rules"][0]["domain_suffix"] == []
    assert changes == [{"rule": 0, "keyword": ["google"], "removed_domains": 0, "removed_suffixes": 8}]


def test_topic_keyword_replaces_all_contained_domain_rules():
    source = {
        "version": 1,
        "rules": [{
            "domain": [
                "google.com", "ggoogle.com", "withgoogle.com", "googleapis.com",
                "googleusercontent.com", "adservice.google.com", "analytics.google.com", "other.net",
            ],
            "domain_suffix": ["google.co.jp", "google.co.uk", "youtube.com"],
        }],
        "source": "geosite-google.json",
    }
    optimized, changes = module.optimize(source, lossy_keywords=True)
    rule = optimized["rules"][0]
    assert rule["domain_keyword"] == ["google"]
    assert rule["domain"] == ["other.net"]
    assert rule["domain_suffix"] == ["youtube.com"]
    assert changes == [{"rule": 0, "keyword": ["google"], "removed_domains": 7, "removed_suffixes": 2}]


def test_default_mode_keeps_exact_rule_entries():
    source = {
        "version": 1,
        "rules": [{"domain": list(GOOGLE_GROUP)}],
        "source": "geosite-google@cn.json",
    }
    optimized, changes = module.optimize(source)
    assert optimized["rules"][0]["domain"] == GOOGLE_GROUP
    assert "domain_keyword" not in optimized["rules"][0]
    assert changes == []


def test_inverted_rule_is_never_rewritten():
    source = {
        "version": 1,
        "rules": [{"domain": list(GOOGLE_GROUP), "invert": True}],
        "source": "geosite-google@cn.json",
    }
    optimized, changes = module.optimize(source, lossy_keywords=True)
    rule = optimized["rules"][0]
    assert rule["domain"] == GOOGLE_GROUP
    assert rule["invert"] is True
    assert "domain_keyword" not in rule
    assert changes == []


def test_extra_condition_blocks_rewrite():
    source = {
        "version": 1,
        "rules": [{"domain": list(GOOGLE_GROUP), "port": [443]}],
        "source": "geosite-google@cn.json",
    }
    optimized, changes = module.optimize(source, lossy_keywords=True)
    rule = optimized["rules"][0]
    assert rule["domain"] == GOOGLE_GROUP
    assert rule["port"] == [443]
    assert "domain_keyword" not in rule
    assert changes == []


def test_logical_rule_is_not_rewritten():
    source = {
        "version": 1,
        "rules": [{"type": "logical", "mode": "and", "rules": [{"domain": list(GOOGLE_GROUP)}]}],
        "source": "geosite-google@cn.json",
    }
    optimized, changes = module.optimize(source, lossy_keywords=True)
    assert optimized["rules"][0] == source["rules"][0]
    assert changes == []


def test_topics_are_not_injected_into_other_rules():
    source = {
        "version": 1,
        "rules": [
            {"domain": list(GOOGLE_GROUP), "port": [443]},
            {"domain": ["other.example"]},
        ],
        "source": "geosite-google@cn.json",
    }
    optimized, changes = module.optimize(source, lossy_keywords=True)
    assert optimized["rules"][1] == {"domain": ["other.example"]}
    assert changes == []


def test_non_string_domain_value_is_rejected():
    source = {
        "version": 1,
        "source": "geosite-google.json",
        "rules": [{"domain": list(GOOGLE_GROUP)}, {"domain": [None]}],
    }
    try:
        module.optimize(source, lossy_keywords=True)
    except ValueError:
        pass
    else:
        raise AssertionError("non-string domain was accepted")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all optimization tests passed")
