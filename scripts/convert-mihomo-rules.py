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
    for rule in document.get("rules", []):
        for key, raw in rule.items():
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, str):
                items = [raw]
            else:
                items = []
            values.setdefault(key, []).extend(str(value) for value in items)
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
                item = item.strip()
                if not item:
                    continue
                if key == "domain_suffix" and item.startswith("."):
                    # sing-box allows a leading dot (".xbox"); mihomo trie
                    # rejects "+..xbox", so normalize to "+.xbox".
                    item = item.lstrip(".")
                    if not item:  # "." matches everything; trie cannot express it
                        skipped.setdefault("domain_suffix", 0)
                        skipped["domain_suffix"] += 1
                        continue
                lines.append(f"{prefix}{item}")
        for key in ("domain_keyword", "domain_regex"):
            if values.get(key):
                skipped[key] = len(values[key])
    elif behavior == "ipcidr":
        for key in ("ip_cidr", "ip_cidr6"):
            for item in values.get(key, []):
                item = item.strip()
                if item:
                    lines.append(item)
        for key in ("geoip", "asn"):
            if values.get(key):
                skipped[key] = len(values[key])
    else:
        raise ValueError(f"unknown behavior: {behavior}")
    return lines, skipped


def _render_yaml(lines):
    return "payload:\n" + "".join(f"    - {line}\n" for line in lines)


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
