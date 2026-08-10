#!/usr/bin/env bash
set -euo pipefail

SOURCE=${1:-}
ROOT=${GITHUB_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
case "$SOURCE" in
  egern|loon|surge) TARGET_BRANCH=$SOURCE ;;
  *) echo "unknown platform branch: $SOURCE" >&2; exit 2 ;;
esac

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
ORIGIN="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}.git"
SOURCE_REF=$(git -C "$ROOT" ls-remote --heads origin sing-geosite)
if [[ -z "$SOURCE_REF" ]]; then
  echo "sing-geosite branch is required before platform conversion" >&2
  exit 1
fi
git -C "$ROOT" fetch --no-tags --quiet origin sing-geosite
mkdir -p "$WORK/source" "$WORK/output"
git -C "$ROOT" archive --format=tar origin/sing-geosite '*.json' | tar -xf - -C "$WORK/source"
json_count=$(find "$WORK/source" -maxdepth 1 -type f -name '*.json' | wc -l)
if ((json_count == 0)); then
  echo "sing-geosite has no JSON artifacts" >&2
  exit 1
fi
python3 "$ROOT/scripts/convert-geosite-rules.py" "$WORK/source" "$WORK/output" "$SOURCE" >"$WORK/convert.json"

TARGET=$(mktemp -d)
trap 'rm -rf "$WORK" "$TARGET"' EXIT
if git -C "$ROOT" ls-remote --exit-code --heads origin "$TARGET_BRANCH" >/dev/null 2>&1; then
  git clone --quiet --no-checkout "$ROOT" "$TARGET"
  git -C "$TARGET" remote set-url origin "$ORIGIN"
  git -C "$TARGET" fetch --no-tags --quiet origin "$TARGET_BRANCH"
  git -C "$TARGET" checkout --quiet -B "$TARGET_BRANCH" FETCH_HEAD
else
  git init --quiet -b "$TARGET_BRANCH" "$TARGET"
  git -C "$TARGET" remote add origin "$ORIGIN"
fi
git -C "$TARGET" config http.https://github.com/.extraheader "AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GITHUB_TOKEN:?GITHUB_TOKEN is required}" | base64 -w0)"
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a "$WORK/output/." "$TARGET/"
git -C "$TARGET" add -A
git -C "$TARGET" config user.name 'github-actions[bot]'
git -C "$TARGET" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$TARGET" commit --allow-empty --quiet -m "chore: sync $SOURCE $(date -u +%F)"
git -C "$TARGET" push --quiet origin "HEAD:$TARGET_BRANCH"
printf 'platform=%s files=%s\n' "$SOURCE" "$(find "$TARGET" -maxdepth 1 -type f | wc -l)"
