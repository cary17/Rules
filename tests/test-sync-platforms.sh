#!/usr/bin/env bash
# End-to-end test for sync-platforms.sh against a throwaway local Git origin.
# Verifies that a conversion with no publishable rules never replaces or
# creates an artifact branch, while a convertible run still publishes.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT="$ROOT/scripts/sync-platforms.sh"
CONVERTER="$ROOT/scripts/convert-geosite-rules.py"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[[ -x "$SCRIPT" ]] || fail "platform sync script is not executable"

TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
ORIGIN_ROOT="$TEST_ROOT/origin"
ORIGIN="$ORIGIN_ROOT/fixture.git"
WORKSPACE="$TEST_ROOT/workspace"
mkdir -p "$ORIGIN_ROOT" "$WORKSPACE/scripts"

git init --quiet --bare --initial-branch=main "$ORIGIN"
cp "$CONVERTER" "$WORKSPACE/scripts/convert-geosite-rules.py"
git -C "$WORKSPACE" init --quiet --initial-branch=main
git -C "$WORKSPACE" config user.name 'rules test'
git -C "$WORKSPACE" config user.email 'rules-test@example.invalid'
git -C "$WORKSPACE" remote add origin "$ORIGIN"
git -C "$WORKSPACE" add scripts
git -C "$WORKSPACE" commit --quiet -m 'chore: fixture workspace'

run_sync() {
  GITHUB_WORKSPACE="$WORKSPACE" \
    GITHUB_SERVER_URL="$ORIGIN_ROOT" \
    GITHUB_REPOSITORY=fixture \
    GITHUB_TOKEN=test-token \
    bash "$SCRIPT" "$1"
}

# sing-geosite artifact branch holding only a rule type Surge cannot express.
printf '%s\n' '{"version":1,"rules":[{"domain_regex":"^example\\.com$"}]}' \
  >"$WORKSPACE/geosite-regex-only.json"
git -C "$WORKSPACE" checkout --quiet -b sing-geosite
git -C "$WORKSPACE" add geosite-regex-only.json
git -C "$WORKSPACE" commit --quiet -m 'chore: sing-geosite fixture'
git -C "$WORKSPACE" push --quiet origin sing-geosite

# A missing target branch must not be created from an empty conversion.
if run_sync surge >"$TEST_ROOT/missing.out" 2>"$TEST_ROOT/missing.err"; then
  fail "all-skipped conversion reported success for a missing branch"
fi
grep -q 'no publishable rule files' "$TEST_ROOT/missing.err" || fail "missing zero-output error message"
if git -C "$ORIGIN" rev-parse --verify --quiet surge >/dev/null; then
  fail "empty conversion created the surge branch"
fi
printf 'PASS: empty conversion does not create a branch\n'

# Existing surge artifacts must survive an all-skipped conversion.
git -C "$WORKSPACE" checkout --quiet main
printf 'DOMAIN,old.example\n' >"$WORKSPACE/old.list"
git -C "$WORKSPACE" checkout --quiet -b surge
git -C "$WORKSPACE" add old.list
git -C "$WORKSPACE" commit --quiet -m 'chore: surge fixture'
git -C "$WORKSPACE" push --quiet origin surge
old_surge=$(git -C "$ORIGIN" rev-parse surge)
old_surge_tree=$(git -C "$ORIGIN" ls-tree -r --name-only surge)

if run_sync surge >"$TEST_ROOT/skipped.out" 2>"$TEST_ROOT/skipped.err"; then
  fail "all-skipped conversion reported success with an existing branch"
fi
grep -q 'no publishable rule files' "$TEST_ROOT/skipped.err" || fail "missing zero-output error message"
[[ "$(git -C "$ORIGIN" rev-parse surge)" == "$old_surge" ]] || fail "existing surge head moved"
[[ "$(git -C "$ORIGIN" ls-tree -r --name-only surge)" == "$old_surge_tree" ]] || fail "existing surge artifacts changed"
printf 'PASS: empty conversion keeps the previous branch\n'

# A convertible run still publishes and replaces stale artifacts.
git -C "$WORKSPACE" checkout --quiet sing-geosite
printf '%s\n' '{"version":1,"rules":[{"domain":["example.com"]}]}' \
  >"$WORKSPACE/geosite-supported.json"
git -C "$WORKSPACE" add geosite-supported.json
git -C "$WORKSPACE" commit --quiet -m 'chore: add convertible rule'
git -C "$WORKSPACE" push --quiet origin sing-geosite
git -C "$WORKSPACE" checkout --quiet surge

run_sync surge >"$TEST_ROOT/success.out" 2>"$TEST_ROOT/success.err" \
  || fail "convertible run failed"
grep -qx 'supported.list' <(git -C "$ORIGIN" ls-tree --name-only surge) \
  || fail "convertible rule was not published"
[[ "$(git -C "$ORIGIN" rev-parse surge)" != "$old_surge" ]] || fail "surge branch was not updated"
grep -q 'successful=1' "$TEST_ROOT/success.out" || fail "summary does not report the successful count"
printf 'PASS: convertible run publishes rules\n'

printf 'all platform sync tests passed\n'
