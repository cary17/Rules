#!/usr/bin/env python3
"""Rule-set JSON optimizer.

Default behaviour is match preserving. Keyword compression is opt-in through
``--lossy-keywords`` (or ``lossy_keywords=True``) because ``domain_keyword``
also matches hosts that the original exact entries did not cover.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

MIN_GROUP_SIZE = 8
MIN_KEYWORD_LENGTH = 5
MIN_SCOPE_COUNT = 8
COMMON_TLDS = {
    "com", "net", "org", "edu", "gov", "mil", "int", "io", "ai", "app",
    "dev", "co", "uk", "us", "cn", "jp", "de", "fr", "ru", "info", "biz",
}
GENERIC_ROOTS = {
    "www", "mail", "api", "cdn", "static", "img", "images", "assets",
    "redirector", "download", "content", "connect", "service", "services",
}


def _values(rule, key):
    value = rule.get(key, [])
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _topic_name(source_name):
    stem = Path(source_name).stem.lower()
    if stem.startswith("geosite-"):
        stem = stem.removeprefix("geosite-")
    stem = stem.split("@", 1)[0]
    for suffix in ("-cn", "-!cn", "-ads", "-!ads"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _candidate_groups(domains):
    groups = defaultdict(list)
    for domain in domains:
        labels = domain.split(".")
        if len(labels) < 3 or any(not label for label in labels):
            continue
        prefix = ".".join(labels[:-1])
        suffix = labels[-1]
        if "." not in prefix or not suffix:
            continue
        groups[prefix].append((domain, suffix))
    return groups


def _topic_roots(scope_values, source_name=""):
    roots = set()
    raw_stem = Path(source_name).stem.lower()
    if not raw_stem.startswith("geosite-"):
        return roots
    stem = _topic_name(source_name)
    if not stem:
        return roots
    roots.add(stem)
    counts = defaultdict(int)
    for value in scope_values:
        labels = value.split(".")
        if labels and labels[0]:
            counts[labels[0].lower()] += 1
    roots.update(root for root, count in counts.items() if count >= MIN_SCOPE_COUNT)
    return roots


def _safe_keyword(prefix, members, scope_values, topic_roots):
    labels = prefix.split(".")
    if len(labels) < 2 or len(prefix) < MIN_KEYWORD_LENGTH:
        return False
    if not re.match(r"^[a-z]", prefix, re.IGNORECASE):
        return False
    if labels[0].lower() in GENERIC_ROOTS or labels[0].lower() not in topic_roots:
        return False
    if labels[0].lower() in COMMON_TLDS:
        return False
    suffixes = [suffix for _, suffix in members]
    if len(members) < MIN_GROUP_SIZE or len(set(suffixes)) != len(suffixes):
        return False
    # The keyword must be a meaningful scope of this rule set, not an
    # accidental shared fragment appearing in only a few unrelated entries.
    return sum(prefix in value for value in scope_values) >= MIN_SCOPE_COUNT


def _in_topic(value, topic_roots):
    value = value.lower()
    return any(root in value for root in topic_roots)


def _rule_is_eligible(rule):
    """Return True only for a plain AND group of domain matchers.

    Inverted rules, logical rules and rules carrying extra conditions (port,
    network, process, ...) stay untouched: swapping their exact values for
    substring keywords changes the matched set, and for inverted rules it also
    flips the outcome for hosts that used to match.
    """
    if rule.get("invert"):
        return False
    if rule.get("type") not in (None, "default"):
        return False
    return not (set(rule) - {"domain", "domain_suffix", "domain_keyword", "type", "invert"})


def _order_rule(rule):
    ordered = {}
    for key in ("domain", "domain_suffix", "domain_keyword"):
        if key in rule:
            ordered[key] = rule[key]
    for key, value in rule.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def optimize(document, lossy_keywords=False):
    """Return (optimized document, change log).

    Without ``lossy_keywords`` the result keeps the exact matched set. Keyword
    compression is never equivalent to domain/domain_suffix entries, because
    ``domain_keyword`` also matches unrelated hosts, so it must be requested
    explicitly and is always reported per rule.
    """
    optimized = {"version": document["version"], "rules": []}
    changes = []
    scope_values = []
    for source_rule in document["rules"]:
        for key in ("domain", "domain_suffix"):
            values = _values(source_rule, key)
            scope_values.extend(str(value) for value in values)
    topic_roots = sorted(_topic_roots(scope_values, document.get("source", "")))
    active_topics = [
        topic for topic in topic_roots
        if len(topic) >= MIN_KEYWORD_LENGTH
        and re.match(r"^[a-z]", topic, re.IGNORECASE)
        and topic not in GENERIC_ROOTS
        and topic not in COMMON_TLDS
        and sum(topic in value.lower() for value in scope_values) >= MIN_SCOPE_COUNT
    ]

    for index, source_rule in enumerate(document["rules"]):
        rule = dict(source_rule)
        if not lossy_keywords or not _rule_is_eligible(rule):
            optimized["rules"].append(_order_rule(rule))
            continue
        original_domains = list(_values(rule, "domain"))
        original_suffixes = list(_values(rule, "domain_suffix"))
        removed_domains = [
            value for value in original_domains
            if any(topic in value.lower() for topic in active_topics)
        ]
        removed_suffixes = [
            value for value in original_suffixes
            if any(topic in value.lower() for topic in active_topics)
        ]
        if not removed_domains and not removed_suffixes:
            optimized["rules"].append(_order_rule(rule))
            continue
        replaced = removed_domains + removed_suffixes
        # Only topics this rule itself contributed may become a keyword: adding
        # every file level topic would widen unrelated rules.
        topics = [topic for topic in active_topics if any(topic in value.lower() for value in replaced)]
        existing_keywords = list(_values(rule, "domain_keyword"))
        added_keywords = [topic for topic in topics if topic not in existing_keywords]
        if removed_domains:
            removed = set(removed_domains)
            rule["domain"] = [value for value in original_domains if value not in removed]
        if removed_suffixes:
            removed = set(removed_suffixes)
            rule["domain_suffix"] = [value for value in original_suffixes if value not in removed]
        if added_keywords:
            rule["domain_keyword"] = existing_keywords + added_keywords
        changes.append({
            "rule": index,
            "keyword": added_keywords or existing_keywords,
            "removed_domains": len(removed_domains),
            "removed_suffixes": len(removed_suffixes),
        })
        optimized["rules"].append(_order_rule(rule))
    return optimized, changes


def convert_file(source, output, source_name=None, lossy_keywords=False):
    document = json.loads(Path(source).read_text(encoding="utf-8"))
    optimized, changes = optimize(
        {**document, "source": source_name or Path(source).name},
        lossy_keywords=lossy_keywords,
    )
    Path(output).write_text(json.dumps(optimized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes


def main(argv):
    args = list(argv[1:])
    lossy_keywords = "--lossy-keywords" in args
    args = [argument for argument in args if argument != "--lossy-keywords"]
    if len(args) not in (2, 3):
        print(f"usage: {argv[0]} INPUT OUTPUT [SOURCE_NAME] [--lossy-keywords]", file=sys.stderr)
        return 2
    changes = convert_file(args[0], args[1], args[2] if len(args) == 3 else None, lossy_keywords)
    print(json.dumps({"changes": changes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
