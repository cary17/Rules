#!/usr/bin/env bash
set -euo pipefail

SOURCE=${1:-}
ROOT=${GITHUB_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
case "$SOURCE" in
  sing-geoip|sing-geosite) TARGET_BRANCH=$SOURCE ;;
  *) echo "unknown artifact branch: $SOURCE" >&2; exit 2 ;;
esac
TARGET=$(mktemp -d)
LOG=$(mktemp)
trap 'rm -rf "$TARGET" "$LOG"' EXIT

origin="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}.git"
remote_ref=
if ! remote_ref=$(git -C "$ROOT" ls-remote --heads origin "refs/heads/$TARGET_BRANCH"); then
  echo "$SOURCE: unable to inspect artifact branch" >&2
  exit 1
fi
if [[ -n "$remote_ref" ]]; then
  if ! git -C "$ROOT" fetch --no-tags --quiet origin "$TARGET_BRANCH"; then
    echo "$SOURCE: unable to fetch artifact branch" >&2
    exit 1
  fi
fi
if [[ -n "$remote_ref" ]] && git -C "$ROOT" show-ref --verify --quiet "refs/remotes/origin/$TARGET_BRANCH"; then
  if ! git clone --quiet --no-checkout "$ROOT" "$TARGET"; then
    echo "$SOURCE: unable to clone current checkout" >&2
    exit 1
  fi
  git -C "$TARGET" remote set-url origin "$origin"
  git -C "$TARGET" config http.https://github.com/.extraheader "AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GITHUB_TOKEN:?GITHUB_TOKEN is required}" | base64 -w0)"
  git -C "$TARGET" checkout --quiet "origin/$TARGET_BRANCH"
else
  git init --quiet -b "$TARGET_BRANCH" "$TARGET"
  git -C "$TARGET" remote add origin "$origin"
  git -C "$TARGET" config http.https://github.com/.extraheader "AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GITHUB_TOKEN:?GITHUB_TOKEN is required}" | base64 -w0)"
fi

export RULES_TEST_TARGET_DIR="$TARGET"
SING_BOX_BIN=$(cat /tmp/sing-box-path)
export SING_BOX_BIN
printf 'tool sing_box_version=%s asset=%s archive_sha256=%s binary_sha256=%s\n' \
  "${SING_BOX_VERSION:-}" "${SING_BOX_ASSET:-}" "${SING_BOX_ARCHIVE_SHA256:-}" "${SING_BOX_BINARY_SHA256:-}" >"$LOG"
if RULES_TEST_TARGET_DIR="$TARGET" "$ROOT/scripts/sync-rules.sh" "$SOURCE" >>"$LOG" 2>&1; then
  status=0
else
  status=$?
fi

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

if ((status != 0 && status != 3)); then
  echo "$SOURCE: no publishable result; artifact branch left unchanged" >&2
  exit "$status"
fi

# Artifact branches contain only rule files. Provenance and failures are stored
# in the commit body and GitHub Actions job summary.
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name .git -type f -delete
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name .git -type d -exec rm -rf {} +
git -C "$TARGET" add -A
summary_file=$(mktemp)
commit_message=$(mktemp)
trap 'rm -rf "$TARGET" "$LOG" "$summary_file" "$commit_message"' EXIT
sed -n '/^tool /p; /^source=/p; /^SUCCESS /p; /^FAILED /p; /existing artifacts retained/p' "$LOG" >"$summary_file"
{
  printf 'chore: sync %s %s\n\n' "$SOURCE" "$(date -u +%F)"
  cat "$summary_file"
} >"$commit_message"
git -C "$TARGET" config user.name 'github-actions[bot]'
git -C "$TARGET" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if ! git -C "$TARGET" commit --allow-empty --quiet -F "$commit_message"; then
  echo "$SOURCE: unable to create artifact commit; branch left unchanged" >&2
  exit 1
fi
if ! git -C "$TARGET" push --quiet origin "HEAD:$TARGET_BRANCH"; then
  echo "$SOURCE: unable to publish artifact branch" >&2
  exit 1
fi

if [[ $status -ne 0 ]]; then
  echo "$SOURCE: published successful files; failures remain in summary" >&2
  exit "$status"
fi
exit 0

# shellcheck disable=SC2317
true
