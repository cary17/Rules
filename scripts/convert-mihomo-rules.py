#!/usr/bin/env python3
"""Convert sing-box native rule-set JSON to mihomo rule-set artifacts.

Output format follows MetaCubeX/meta-rules-dat `meta` branch and Yuu-rules:
per source file, a `.list` (bare trie text) and a `.yaml` (payload wrapper).
`.mrs` is generated externally via `mihomo convert-ruleset <behavior> yaml`.

Behavior:
  domain  -> geosite: domain -> bare, domain_suffix -> "+.", domain_wildcard -> "*."
  ipcidr  -> geoip: ip_cidr / ip_cidr6 -> bare CIDR

mihomo trie formats cannot represent domain_keyword / domain_regex / geoip /
asn; those are skipped and reported (same as Yuu-rules).

usage: convert-mihomo-rules.py SOURCE_DIR OUTPUT_DIR domain|ipcidr
"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PREFIX = {"domain": "+.", "domain_suffix": "+.", "domain_wildcard": "*."}
SKIPPED_KEYS = {"domain_keyword", "domain_regex", "geoip", "asn"}


@dataclass
class ConversionResult:
    successful: int
    skipped: int
    skipped_types: dict[str, int]


def _rule_values(document):
    values = {}
    supported = {"domain", "domain_suffix", "domain_wildcard", "domain_keyword", "domain_regex", "ip_cidr", "ip_cidr6", "geoip", "asn"}
    for rule in document.get("rules", []):
        if not isinstance(rule, dict):
            raise ValueError("rule must be an object")
        if rule.get("invert") or rule.get("type") not in (None, "default"):
            raise ValueError("inverted or logical rules are not convertible")
        for key, raw in rule.items():
            if key in {"invert", "type"}:
                continue
            if key not in supported:
                raise ValueError(f"unsupported rule condition: {key}")
            items = raw if isinstance(raw, list) else [raw]
            if any(not isinstance(item, str) for item in items):
                raise ValueError(f"rule condition must contain strings: {key}")
            values.setdefault(key, []).extend(items)
    return values


def _render_trie(values, behavior):
    """Return (list of bare trie lines, skipped-type counts)."""
    lines = []
    skipped = {}
    if behavior == "domain":
        # sing-box domain_wildcard values already carry a "*." or "." prefix,
        # so they are emitted verbatim (no extra prefix).
        for key, prefix in (("domain", ""), ("domain_suffix", "+."), ("domain_wildcard", "")):
            for item in values.get(key, []):
                if not isinstance(item, str) or not item.strip():
                    skipped[key] = skipped.get(key, 0) + 1
                    continue
                item = item.strip()
                if key == "domain_suffix" and item == ".":
                    skipped[key] = skipped.get(key, 0) + 1
                elif key == "domain_suffix" and item.startswith("."):
                    # Mihomo's leading-dot entry means subdomains only.
                    lines.append(item)
                else:
                    lines.append(f"{prefix}{item}")
        for key in ("domain_keyword", "domain_regex"):
            if values.get(key):
                skipped[key] = len(values[key])
    elif behavior == "ipcidr":
        for key in ("ip_cidr", "ip_cidr6"):
            for item in values.get(key, []):
                if isinstance(item, str) and item.strip():
                    lines.append(item.strip())
                else:
                    skipped[key] = skipped.get(key, 0) + 1
        for key in ("geoip", "asn"):
            if values.get(key):
                skipped[key] = len(values[key])
    else:
        raise ValueError(f"unknown behavior: {behavior}")
    return lines, skipped


def _render_yaml(lines):
    return "payload:\n" + "".join(f"    - {json.dumps(line, ensure_ascii=False)}\n" for line in lines)


def _write_atomic(destination, content):
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(destination)


def convert_directory(source_dir, output_dir, behavior):
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = ConversionResult(0, 0, {})
    for source in sorted(source_dir.glob("*.json")):
        document = json.loads(source.read_text(encoding="utf-8"))
        lines, skipped = _render_trie(_rule_values(document), behavior)
        output_stem = source.stem
        for prefix in ("geoip-", "geosite-"):
            output_stem = output_stem.removeprefix(prefix)
        if not lines:
            for extension in (".list", ".yaml"):
                (output_dir / f"{output_stem}{extension}").unlink(missing_ok=True)
        else:
            _write_atomic(output_dir / f"{output_stem}.list", "".join(f"{line}\n" for line in lines))
            _write_atomic(output_dir / f"{output_stem}.yaml", _render_yaml(lines))
            result.successful += 1
        for key, count in skipped.items():
            result.skipped += count
            result.skipped_types[key] = result.skipped_types.get(key, 0) + count
    return result


def main(argv):
    if len(argv) != 4:
        print(f"usage: {argv[0]} SOURCE_DIR OUTPUT_DIR domain|ipcidr", file=sys.stderr)
        return 2
    result = convert_directory(argv[1], argv[2], argv[3])
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
