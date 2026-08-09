#!/usr/bin/env bash
set -u -o pipefail

SOURCE=${1:-}
ROOT=${GITHUB_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
case "$SOURCE" in
  sing-geoip|sing-geosite) TARGET_BRANCH=$SOURCE ;;
  *) echo "unknown artifact branch: $SOURCE" >&2; exit 2 ;;
esac
TARGET=$(mktemp -d)
LOG=$(mktemp)
trap 'rm -rf "$TARGET" "$LOG"' EXIT

origin=$(git -C "$ROOT" remote get-url origin)
git -C "$ROOT" fetch --no-tags --quiet origin "$TARGET_BRANCH" 2>/dev/null || true
if git -C "$ROOT" show-ref --verify --quiet "refs/remotes/origin/$TARGET_BRANCH"; then
  git clone --quiet --no-checkout "$ROOT" "$TARGET"
  git -C "$TARGET" remote set-url origin "$origin"
  git -C "$TARGET" checkout --quiet "origin/$TARGET_BRANCH"
else
  git init --quiet -b "$TARGET_BRANCH" "$TARGET"
  git -C "$TARGET" remote add origin "$origin"
fi

export RULES_TEST_TARGET_DIR="$TARGET"
SING_BOX_BIN=$(cat /tmp/sing-box-path)
export SING_BOX_BIN
printf 'tool sing_box_version=%s asset=%s archive_sha256=%s binary_sha256=%s\n' \
  "${SING_BOX_VERSION:-}" "${SING_BOX_ASSET:-}" "${SING_BOX_ARCHIVE_SHA256:-}" "${SING_BOX_BINARY_SHA256:-}" >"$LOG"
set +e
RULES_TEST_TARGET_DIR="$TARGET" "$ROOT/scripts/sync-rules.sh" "$SOURCE" >>"$LOG" 2>&1
status=$?
set -e

{
  echo "## $SOURCE"
  echo
  sed -n '/^tool /p; /^source=/p; /^SUCCESS /p; /^FAILED /p; /existing artifacts retained/p' "$LOG" || true
  echo
  echo '### Detailed failures'
  echo
  if grep -q '^FAILED ' "$LOG"; then
    echo '```text'
    grep '^FAILED ' "$LOG"
    echo '```'
  else
    echo 'None.'
  fi
} >> "$GITHUB_STEP_SUMMARY"
cat "$LOG"

# Artifact branches contain only rule files. Provenance and failures are stored
# in the commit body and GitHub Actions job summary.
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name .git -type f -delete
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name .git -type d -exec rm -rf {} +
git -C "$TARGET" add -A
summary=$(sed -n '/^tool /p; /^source=/p; /^SUCCESS /p; /^FAILED /p; /existing artifacts retained/p' "$LOG" | head -c 500000)
git -C "$TARGET" commit --allow-empty --quiet -m "chore: sync $SOURCE $(date -u +%F)" -m "$summary"
git -C "$TARGET" push --quiet origin "HEAD:$TARGET_BRANCH"

if [[ $status -ne 0 ]]; then
  echo "$SOURCE: published successful files; failures remain in summary" >&2
  exit "$status"
fi
exit 0

# shellcheck disable=SC2317
true
