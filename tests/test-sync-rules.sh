#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT="$ROOT/scripts/sync-rules.sh"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[[ -x "$SCRIPT" ]] || fail "sync script is not executable"

if "$SCRIPT" invalid >/tmp/rules-invalid.out 2>/tmp/rules-invalid.err; then
  fail "invalid source was accepted"
fi

grep -q 'unknown source' /tmp/rules-invalid.err || fail "invalid source error missing"

printf 'PASS: parameter validation\n'

TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/source" "$TEST_ROOT/target"

cat >"$TEST_ROOT/bin/sing-box" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  rule-set)
    case "${2:-}" in
      decompile)
        case "$3" in
          *geoip-fail.srs) printf 'decompile failed\n' >&2; exit 1 ;;
          *) printf '{"version":1,"rules":[{"domain":["example.com"]}]}\n' > "${5:-}" ;;
        esac
        ;;
      compile) printf 'SRS\001roundtrip\n' > "${5:-}" ;;
      *) exit 2 ;;
    esac
    ;;
  version) printf 'sing-box version 1.0.0\n' ;;
  *) exit 2 ;;
esac
EOF
chmod +x "$TEST_ROOT/bin/sing-box"
printf 'SRS\001test\n' >"$TEST_ROOT/source/geoip-ok.srs"
printf 'SRS\001bad\n' >"$TEST_ROOT/source/geoip-fail.srs"
printf 'SRS\001old\n' >"$TEST_ROOT/target/geoip-fail.srs"
printf '{"version":1,"rules":[{"domain":["old.example"]}]}\n' >"$TEST_ROOT/target/geoip-fail.json"
old_srs_sha=$(sha256sum "$TEST_ROOT/target/geoip-fail.srs" | awk '{print $1}')
old_json_sha=$(sha256sum "$TEST_ROOT/target/geoip-fail.json" | awk '{print $1}')

# The implementation must support a local fixture mode for deterministic tests.
if ! PATH="$TEST_ROOT/bin:$PATH" RULES_TEST_SOURCE_DIR="$TEST_ROOT/source" RULES_TEST_TARGET_DIR="$TEST_ROOT/target" "$SCRIPT" sing-geoip; then
  :
fi

[[ -f "$TEST_ROOT/target/geoip-ok.srs" ]] || fail "successful SRS was not published"
[[ -f "$TEST_ROOT/target/geoip-ok.json" ]] || fail "successful JSON was not published"
[[ "$(sha256sum "$TEST_ROOT/target/geoip-fail.srs" | awk '{print $1}')" == "$old_srs_sha" ]] || fail "failed SRS was overwritten"
[[ "$(sha256sum "$TEST_ROOT/target/geoip-fail.json" | awk '{print $1}')" == "$old_json_sha" ]] || fail "failed JSON was overwritten"
[[ ! -e "$TEST_ROOT/target/SOURCE.json" ]] || fail "metadata leaked into artifact target"
[[ "$(find "$TEST_ROOT/target" -maxdepth 1 -type f -name '*.srs' | wc -l)" == 2 ]] || fail "unexpected SRS count"
[[ "$(find "$TEST_ROOT/target" -maxdepth 1 -type f -name '*.json' | wc -l)" == 2 ]] || fail "unexpected JSON count"
[[ "$(find "$TEST_ROOT/target" -mindepth 1 -maxdepth 1 -type d | wc -l)" == 0 ]] || fail "artifact target contains a directory"

printf 'PASS: successful and failed file handling\n'

printf 'all tests passed\n'