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

# Valid SRS fixtures: the fidelity check decodes the container, so the fake
# compiler has to hand back real rule-set binaries rather than arbitrary bytes.
srs_fixture() {
  python3 - "$1" "$2" <<'PY'
import sys, zlib
# header "SRS" + format version, then a zlib stream over the payload
payload = b"\x01" + sys.argv[1].encode()
open(sys.argv[2], "wb").write(b"SRS\x01" + zlib.compress(payload, 6))
PY
}

cat >"$TEST_ROOT/bin/sing-box" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
# Emulates a faithful compiler: recompiling a decompiled rule-set reproduces the
# rule-set payload upstream published, which is what the real sing-box does. A
# *fidelity* name simulates a lossy recompile (same conditions minus one).
case "${1:-}" in
  rule-set)
    case "${2:-}" in
      decompile)
        case "$3" in
          *geoip-fail.srs) printf 'decompile failed\n' >&2; exit 1 ;;
          *) printf '{"version":1,"rules":[{"domain":["example.com"]}]}\n' > "${5:-}" ;;
        esac
        ;;
      compile)
        base=$(basename "${3:-}" .json)
        base=${base%.roundtrip}
        if [[ "$base" == *fidelity* ]]; then
          cp "$RULES_TEST_SOURCE_DIR/recompiled.srs" "${5:-}"
        else
          cp "$RULES_TEST_SOURCE_DIR/$base.srs" "${5:-}"
        fi
        ;;
      *) exit 2 ;;
    esac
    ;;
  version) printf 'sing-box version 1.0.0\n' ;;
  *) exit 2 ;;
esac
EOF
chmod +x "$TEST_ROOT/bin/sing-box"
export SING_BOX_BIN="$TEST_ROOT/bin/sing-box"
srs_fixture ok "$TEST_ROOT/source/geoip-ok.srs"
srs_fixture bad "$TEST_ROOT/source/geoip-fail.srs"
srs_fixture old "$TEST_ROOT/target/geoip-fail.srs"
printf '{"version":1,"rules":[{"domain":["old.example"]}]}\n' >"$TEST_ROOT/target/geoip-fail.json"
old_srs_sha=$(sha256sum "$TEST_ROOT/target/geoip-fail.srs" | awk '{print $1}')
old_json_sha=$(sha256sum "$TEST_ROOT/target/geoip-fail.json" | awk '{print $1}')

# The implementation must support a local fixture mode for deterministic tests.
if PATH="$TEST_ROOT/bin:$PATH" RULES_TEST_SOURCE_DIR="$TEST_ROOT/source" RULES_TEST_TARGET_DIR="$TEST_ROOT/target" "$SCRIPT" sing-geoip; then
  fail "partially failed run reported success"
else
  [[ "$?" == 3 ]] || fail "partial failure did not return exit code 3"
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

# A failed first run must not create metadata or partial output.
mkdir -p "$TEST_ROOT/source-all-failed"
srs_fixture bad "$TEST_ROOT/source-all-failed/geoip-fail.srs"
rm -rf "$TEST_ROOT/target" && mkdir -p "$TEST_ROOT/target"
if PATH="$TEST_ROOT/bin:$PATH" RULES_TEST_SOURCE_DIR="$TEST_ROOT/source-all-failed" RULES_TEST_TARGET_DIR="$TEST_ROOT/target" "$SCRIPT" sing-geoip >/tmp/rules-empty-run.out 2>/tmp/rules-empty-run.err; then
  fail "all-failed run was accepted"
fi
[[ "$(find "$TEST_ROOT/target" -mindepth 1 -maxdepth 1 -type f | wc -l)" == 0 ]] || fail "all-failed run published artifacts"
[[ "$(find "$TEST_ROOT/target" -mindepth 1 -maxdepth 1 -type d | wc -l)" == 0 ]] || fail "all-failed run created directories"
printf 'PASS: all-failed run is not published\n'

# A lossy recompile must be caught even though the decompiled JSON stays stable,
# and the previous artifact pair must survive untouched.
mkdir -p "$TEST_ROOT/source-fidelity"
srs_fixture upstream "$TEST_ROOT/source-fidelity/geoip-fidelity.srs"
srs_fixture lossy "$TEST_ROOT/source-fidelity/recompiled.srs"
rm -rf "$TEST_ROOT/target" && mkdir -p "$TEST_ROOT/target"
srs_fixture old "$TEST_ROOT/target/geoip-fidelity.srs"
printf '{"version":1,"rules":[{"domain":["old.example"]}]}\n' >"$TEST_ROOT/target/geoip-fidelity.json"
fidelity_srs=$(sha256sum "$TEST_ROOT/target/geoip-fidelity.srs" | awk '{print $1}')
fidelity_json=$(sha256sum "$TEST_ROOT/target/geoip-fidelity.json" | awk '{print $1}')
if PATH="$TEST_ROOT/bin:$PATH" RULES_TEST_SOURCE_DIR="$TEST_ROOT/source-fidelity" RULES_TEST_TARGET_DIR="$TEST_ROOT/target" "$SCRIPT" sing-geoip >/tmp/rules-fidelity.out 2>/tmp/rules-fidelity.err; then
  fail "lossy recompile was accepted"
fi
grep -q 'stage=roundtrip_fidelity' /tmp/rules-fidelity.err || fail "fidelity failure was not reported"
[[ "$(sha256sum "$TEST_ROOT/target/geoip-fidelity.srs" | awk '{print $1}')" == "$fidelity_srs" ]] || fail "fidelity failure overwrote old SRS"
[[ "$(sha256sum "$TEST_ROOT/target/geoip-fidelity.json" | awk '{print $1}')" == "$fidelity_json" ]] || fail "fidelity failure overwrote old JSON"
printf 'PASS: lossy recompile is rejected and old artifacts survive\n'

# A failed final copy must restore the byte-identical old artifact pair.
rm -rf "$TEST_ROOT/target" && mkdir -p "$TEST_ROOT/target"
srs_fixture old "$TEST_ROOT/target/geoip-ok.srs"
printf '{"version":1,"rules":[{"domain":["old.example"]}]}\n' >"$TEST_ROOT/target/geoip-ok.json"
old_srs=$(sha256sum "$TEST_ROOT/target/geoip-ok.srs" | awk '{print $1}')
old_json=$(sha256sum "$TEST_ROOT/target/geoip-ok.json" | awk '{print $1}')
cat >"$TEST_ROOT/bin/cp" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"/publish/."* ]]; then /bin/cp "$@"; exit 1; fi
exec /bin/cp "$@"
EOF
chmod +x "$TEST_ROOT/bin/cp"
if PATH="$TEST_ROOT/bin:$PATH" RULES_TEST_SOURCE_DIR="$TEST_ROOT/source" RULES_TEST_TARGET_DIR="$TEST_ROOT/target" "$SCRIPT" sing-geoip >/tmp/rules-copy-fail.out 2>/tmp/rules-copy-fail.err; then
  fail "final copy failure was accepted"
fi
[[ "$(sha256sum "$TEST_ROOT/target/geoip-ok.srs" | awk '{print $1}')" == "$old_srs" ]] || fail "final copy failure lost old SRS"
[[ "$(sha256sum "$TEST_ROOT/target/geoip-ok.json" | awk '{print $1}')" == "$old_json" ]] || fail "final copy failure lost old JSON"
printf 'PASS: final copy failure restores old artifacts\n'

printf 'all tests passed\n'
