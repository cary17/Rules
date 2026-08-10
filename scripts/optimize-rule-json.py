#!/usr/bin/env python3
import json
import sys
from collections import defaultdict
from pathlib import Path

MIN_GROUP_SIZE = 8
MIN_KEYWORD_LENGTH = 6
MIN_SCOPE_COUNT = 8
COMMON_TLDS = {
    "com", "net", "org", "edu", "gov", "mil", "int", "io", "ai", "app",
    "dev", "co", "uk", "us", "cn", "jp", "de", "fr", "ru", "info", "biz",
}
GENERIC_ROOTS = {"www", "mail", "api", "cdn", "static", "img", "images", "assets"}


def _values(rule, key):
    value = rule.get(key, [])
    return value if isinstance(value, list) else []


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
    stem = Path(source_name).stem.lower()
    if stem.startswith("geosite-"):
        roots.add(stem.removeprefix("geosite-").split("@", 1)[0])
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


def optimize(document):
    optimized = {"version": document["version"], "rules": []}
    changes = []
    scope_values = []
    for source_rule in document["rules"]:
        for key, values in source_rule.items():
            if isinstance(values, list):
                scope_values.extend(str(value) for value in values)
    topic_roots = _topic_roots(scope_values, document.get("source", ""))
    for source_rule in document["rules"]:
        rule = dict(source_rule)
        domains = list(_values(rule, "domain"))
        groups = _candidate_groups(domains)
        consumed = set()
        keywords = []
        all_match_values = []
        suffix_rules = set(_values(source_rule, "domain_suffix"))
        exact_rules = set(domains)
        for key, values in source_rule.items():
            if key != "domain":
                all_match_values.extend(str(value) for value in _values(source_rule, key))
        for prefix, members in sorted(groups.items()):
            target_domains = {domain for domain, _ in members}
            if not _safe_keyword(prefix, members, domains + list(suffix_rules) + all_match_values, topic_roots):
                continue
            unsafe_known_match = False
            for value in all_match_values:
                if prefix not in value:
                    continue
                # A topic-scoped rule set may deliberately broaden matching
                # within its own named topic. Values outside that topic remain
                # a hard boundary.
                if _in_topic(value, topic_roots):
                    continue
                if value == prefix or value in target_domains or value in exact_rules:
                    continue
                if value in suffix_rules:
                    continue
                unsafe_known_match = True
                break
            if unsafe_known_match or len(members) < MIN_GROUP_SIZE:
                continue

            suffixes = [suffix for _, suffix in members]
            if len(set(suffixes)) != len(suffixes):
                continue
            keywords.append(prefix)
            consumed.update(domain for domain, _ in members)
            changes.append({"keyword": prefix, "replaced_domains": len(members)})
        if consumed:
            rule["domain"] = [domain for domain in domains if domain not in consumed]
        suffix_values = list(_values(rule, "domain_suffix"))
        suffix_groups = _candidate_groups(suffix_values)
        suffix_consumed = set()
        suffix_keywords = []
        for prefix, members in sorted(suffix_groups.items()):
            if not _safe_keyword(prefix, members, suffix_values + all_match_values, topic_roots):
                continue
            target_values = {value for value, _ in members}
            if any(
                prefix in value
                and value != prefix
                and value not in target_values
                and not _in_topic(value, topic_roots)
                for value in all_match_values
            ):
                continue
            suffix_keywords.append(prefix)
            suffix_consumed.update(target_values)
            changes.append({"keyword": prefix, "replaced_suffixes": len(members)})
        if suffix_consumed:
            rule["domain_suffix"] = [value for value in suffix_values if value not in suffix_consumed]
        if keywords:
            rule["domain_keyword"] = list(_values(rule, "domain_keyword")) + keywords
        if suffix_keywords:
            rule["domain_keyword"] = list(_values(rule, "domain_keyword")) + suffix_keywords
        # Explicit field order keeps keyword rules after exact and suffix rules.
        ordered = {}
        for key in ("domain", "domain_suffix", "domain_keyword"):
            if key in rule:
                ordered[key] = rule[key]
        for key, value in rule.items():
            if key not in ordered:
                ordered[key] = value
        optimized["rules"].append(ordered)
    return optimized, changes


def convert_file(source, output, source_name=None):
    document = json.loads(Path(source).read_text(encoding="utf-8"))
    optimized, changes = optimize({**document, "source": source_name or Path(source).name})
    Path(output).write_text(json.dumps(optimized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes


def main(argv):
    if len(argv) not in (3, 4):
        print(f"usage: {argv[0]} INPUT OUTPUT [SOURCE_NAME]", file=sys.stderr)
        return 2
    changes = convert_file(argv[1], argv[2], argv[3] if len(argv) == 4 else None)
    print(json.dumps({"changes": changes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
