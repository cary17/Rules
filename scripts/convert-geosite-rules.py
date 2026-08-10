#!/usr/bin/env python3
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

EGERN_TYPES = {
    "domain": "domain_set",
    "domain_suffix": "domain_suffix_set",
    "domain_keyword": "domain_keyword_set",
    "domain_regex": "domain_regex_set",
    "domain_wildcard": "domain_wildcard_set",
    "geoip": "geoip_set",
    "ip_cidr": "ip_cidr_set",
    "ip_cidr6": "ip_cidr6_set",
    "asn": "asn_set",
}
CLIENT_TYPES = {
    "domain": "DOMAIN",
    "domain_suffix": "DOMAIN-SUFFIX",
    "domain_keyword": "DOMAIN-KEYWORD",
    "geoip": "GEOIP",
    "ip_cidr": "IP-CIDR",
    "ip_cidr6": "IP-CIDR6",
    "asn": "IP-ASN",
}
IP_TYPES = {"geoip", "ip_cidr", "ip_cidr6", "asn"}


@dataclass
class ConversionResult:
    successful: int
    skipped: int
    skipped_types: dict[str, int]


def _rule_values(document):
    values = {}
    for rule in document.get("rules", []):
        for key, raw in rule.items():
            if isinstance(raw, list):
                values.setdefault(key, []).extend(str(value) for value in raw)
    return values


def _metadata(name, total, skipped):
    text = [f"# 规则名称: {name}", f"# 更新时间: {date.today().isoformat()}"]
    skipped_total = sum(skipped.values())
    detail = f"原生规则={total}; 可表达规则={total - skipped_total}"
    if skipped:
        detail += "; 跳过规则=" + ",".join(f"{key}={value}" for key, value in skipped.items())
    else:
        detail += "; 跳过规则=0"
    text.append(f"# 规则数量统计: {detail}")
    return text


def _plain(value):
    value = str(value).replace("\r", " ").replace("\n", " ")
    if "\n" in value or value.startswith("#"):
        raise ValueError("rule value cannot be represented without quotes")
    return value


def render_egern(document, name=None):
    values = _rule_values(document)
    name = name or document.get("name", "Rules")
    total = sum(len(items) for items in values.values())
    lines = _metadata(name, total, {})
    if any(values.get(key) for key in IP_TYPES):
        lines.append("no_resolve: true")
    for source_type, target_type in EGERN_TYPES.items():
        items = values.get(source_type, [])
        if not items:
            continue
        lines.append(f"{target_type}:")
        lines.extend(f"  - {_plain(item)}" for item in items)
    return "\n".join(lines) + "\n", []


def render_client(document, name=None):
    values = _rule_values(document)
    name = name or document.get("name", "Rules")
    skipped = {
        key: len(values.get(key, []))
        for key in values
        if key not in CLIENT_TYPES and values.get(key)
    }
    total = sum(len(items) for items in values.values())
    lines = _metadata(name, total, skipped)
    for source_type, target_type in CLIENT_TYPES.items():
        lines.extend(f"{target_type},{_plain(item)}" for item in values.get(source_type, []))
    return "\n".join(lines) + "\n", list(skipped.items())


def render_surge(document, name=None):
    return render_client(document, name)


def render_loon(document, name=None):
    return render_client(document, name)


def render(document, target, name=None):
    if target == "egern":
        return render_egern(document, name)
    if target in {"loon", "surge"}:
        return render_client(document, name)
    raise ValueError(f"unknown target: {target}")


def convert_directory(source_dir, output_dir, target):
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    successful = 0
    skipped = 0
    skipped_types = {}
    extension = {"egern": ".yaml", "loon": ".list", "surge": ".list"}[target]
    for source in sorted(source_dir.glob("*.json")):
        document = json.loads(source.read_text(encoding="utf-8"))
        display_name = source.stem.removeprefix("geosite-")
        rendered, details = render(document, target, display_name)
        temporary = output_dir / f".{source.stem}{extension}.tmp"
        destination = output_dir / f"{source.stem}{extension}"
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(destination)
        successful += 1
        for key, count in details:
            skipped += count
            skipped_types[key] = skipped_types.get(key, 0) + count
    return ConversionResult(successful, skipped, skipped_types)


def main(argv):
    if len(argv) != 4:
        print(f"usage: {argv[0]} SOURCE_DIR OUTPUT_DIR egern|loon|surge", file=sys.stderr)
        return 2
    result = convert_directory(argv[1], argv[2], argv[3])
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
