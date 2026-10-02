#!/usr/bin/env bash
# End-to-end test for sync-mihomo.sh against a throwaway local Git origin with
# a stub compiler. Verifies that an all-skipped conversion never publishes an
# empty artifact branch.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT="$ROOT/scripts/sync-mihomo.sh"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[[ -x "$SCRIPT" ]] || fail "mihomo sync script is not executable"

TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
ORIGIN_ROOT="$TEST_ROOT/origin"
ORIGIN="$ORIGIN_ROOT/fixture.git"
WORKSPACE="$TEST_ROOT/workspace"
BIN="$TEST_ROOT/bin"
mkdir -p "$ORIGIN_ROOT" "$WORKSPACE/scripts" "$BIN"

# Stub compiler: writes a placeholder .mrs for the given yaml path.
cat >"$BIN/mihomo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == convert-ruleset ]] || exit 2
cp "$4" "$5"
EOF
chmod +x "$BIN/mihomo"

cp "$ROOT/scripts/convert-mihomo-rules.py" "$WORKSPACE/scripts/convert-mihomo-rules.py"
git init --quiet --bare --initial-branch=main "$ORIGIN"
git -C "$WORKSPACE" init --quiet --initial-branch=main
git -C "$WORKSPACE" config user.name 'rules test'
git -C "$WORKSPACE" config user.email 'rules-test@example.invalid'
git -C "$WORKSPACE" remote add origin "$ORIGIN"
git -C "$WORKSPACE" add scripts
git -C "$WORKSPACE" commit --quiet -m 'chore: fixture workspace'

run_sync() {
  PATH="$BIN:$PATH" \
    GITHUB_WORKSPACE="$WORKSPACE" \
    GITHUB_SERVER_URL="$ORIGIN_ROOT" \
    GITHUB_REPOSITORY=fixture \
    GITHUB_TOKEN=test-token \
    MIHOMO_BIN="$BIN/mihomo" \
    bash "$SCRIPT" "$1"
}

# geoip passes cannot express domain-only conditions, so nothing is publishable.
printf '%s\n' '{"version":1,"rules":[{"domain_keyword":["example"]}]}' \
  >"$WORKSPACE/geoip-domain-only.json"
git -C "$WORKSPACE" checkout --quiet -b sing-geoip
git -C "$WORKSPACE" add geoip-domain-only.json
git -C "$WORKSPACE" commit --quiet -m 'chore: sing-geoip fixture'
git -C "$WORKSPACE" push --quiet origin sing-geoip

if run_sync geoip >"$TEST_ROOT/skipped.out" 2>"$TEST_ROOT/skipped.err"; then
  fail "all-skipped conversion reported success"
fi
grep -q 'no publishable geoip rule sets' "$TEST_ROOT/skipped.err" || fail "missing zero-output error message"
if git -C "$ORIGIN" rev-parse --verify --quiet mihomo-geoip >/dev/null; then
  fail "empty conversion created the mihomo-geoip branch"
fi
printf 'PASS: empty mihomo conversion does not create a branch\n'

# A convertible run publishes .list/.yaml/.mrs artifacts.
git -C "$WORKSPACE" checkout --quiet sing-geoip
printf '%s\n' '{"version":1,"rules":[{"ip_cidr":["192.0.2.0/24"]}]}' \
  >"$WORKSPACE/geoip-cn.json"
git -C "$WORKSPACE" add geoip-cn.json
git -C "$WORKSPACE" commit --quiet -m 'chore: add convertible geoip rule'
git -C "$WORKSPACE" push --quiet origin sing-geoip

run_sync geoip >"$TEST_ROOT/success.out" 2>"$TEST_ROOT/success.err" \
  || fail "convertible mihomo run failed"
published=$(git -C "$ORIGIN" ls-tree -r --name-only mihomo-geoip | sort | tr '\n' ' ')
for artifact in cn.list cn.yaml cn.mrs; do
  [[ "$published" == *"$artifact"* ]] || fail "missing published artifact: $artifact"
done
printf 'PASS: convertible mihomo run publishes list, yaml and mrs\n'

printf 'all mihomo sync tests passed\n'
