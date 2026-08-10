#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "optimize-rule-json.py"
spec = importlib.util.spec_from_file_location("optimize_rule_json", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_strict_country_suffix_group_becomes_keyword_after_suffixes():
    source = {
        "version": 1,
        "rules": [
            {
                "domain": [
                    "google.co.ao",
                    "google.co.bw",
                    "google.co.ck",
                    "google.co.cr",
                ],
                "domain_suffix": ["google.com"],
            }
        ],
    }
    optimized, changes = module.optimize(source)
    assert optimized["rules"][0]["domain"] == ["google.co.ao", "google.co.bw", "google.co.ck", "google.co.cr"]
    assert optimized["rules"][0].get("domain_keyword", []) == []
    assert changes == []


def test_keyword_requires_exactly_three_or_more_distinct_safe_suffixes():
    source = {
        "version": 1,
        "rules": [
            {
                "domain": [
                    "google.co.ao",
                    "google.co.bw",
                    "google.co.ck",
                    "google.co.cr",
                    "google.co.id",
                    "google.co.il",
                    "google.co.in",
                    "google.co.jp",
                ],
                "domain_suffix": [],
            }
        ],
    }
    optimized, changes = module.optimize(source)
    assert optimized["rules"][0]["domain_keyword"] == ["google.co"]
    assert optimized["rules"][0]["domain"] == []
    assert changes == [{"keyword": "google.co", "replaced_domains": 8}]


def test_large_domain_suffix_group_becomes_keyword():
    source = {
        "version": 1,
        "rules": [{
            "domain": [],
            "domain_suffix": [
                "google.co.ao", "google.co.bw", "google.co.ck", "google.co.cr",
                "google.co.id", "google.co.il", "google.co.in", "google.co.jp",
            ],
        }],
    }
    optimized, changes = module.optimize(source)
    assert optimized["rules"][0]["domain_suffix"] == []
    assert optimized["rules"][0]["domain_keyword"] == ["google.co"]
    assert changes == [{"keyword": "google.co", "replaced_suffixes": 8}]


def test_short_or_top_level_suffix_group_is_not_optimized():
    source = {
        "version": 1,
        "rules": [{
            "domain_suffix": ["com.a", "com.b", "com.c", "com.d", "com.e", "com.f", "com.g", "com.h"],
        }],
    }
    optimized, changes = module.optimize(source)
    assert "domain_keyword" not in optimized["rules"][0]
    assert changes == []


def test_topic_boundary_comes_from_each_rule_set_filename():
    source = {
        "version": 1,
        "rules": [{
            "domain_suffix": [
                "google.co.ao", "google.co.bw", "google.co.ck", "google.co.cr",
                "google.co.id", "google.co.il", "google.co.in", "google.co.jp",
            ],
        }],
        "source": "geosite-google.json",
    }
    optimized, changes = module.optimize(source)
    assert optimized["rules"][0]["domain_keyword"] == ["google.co"]
    assert changes == [{"keyword": "google.co", "replaced_suffixes": 8}]


def test_keyword_is_rejected_when_it_would_match_unrelated_domain():
    source = {
        "version": 1,
        "rules": [
            {
                "domain": [
                    "google.co.ao",
                    "google.co.bw",
                    "google.co.ck",
                    "google.co.cr",
                    "notgoogle.co.example",
                ],
                "domain_suffix": [],
            }
        ],
    }
    optimized, changes = module.optimize(source)
    assert "google.co" not in optimized["rules"][0].get("domain_keyword", [])
    assert len(optimized["rules"][0]["domain"]) == 5
    assert changes == []


def test_keyword_is_emitted_after_domain_and_domain_suffix_fields():
    source = {
        "version": 1,
        "rules": [{
            "domain": [
                "google.co.ao", "google.co.bw", "google.co.ck", "google.co.cr",
                "google.co.id", "google.co.il", "google.co.in", "google.co.jp",
            ],
            "domain_suffix": ["google.com"],
        }],
    }
    optimized, _ = module.optimize(source)
    keys = list(optimized["rules"][0])
    assert keys.index("domain_keyword") > keys.index("domain")
    assert keys.index("domain_keyword") > keys.index("domain_suffix")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all optimization tests passed")

# The optimizer module is intentionally imported before implementation.
