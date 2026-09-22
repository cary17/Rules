#!/usr/bin/env bash
set -euo pipefail

# Sync mihomo rule-set artifacts from sing-box native JSON.
# Usage: sync-mihomo.sh <geoip|geosite>
#   geoip   -> reads sing-geoip *.json, writes mihomo-geoip (.list/.yaml/.mrs)
#   geosite -> reads sing-geosite *.json, writes mihomo-geosite (.list/.yaml/.mrs)
# Requires: GITHUB_TOKEN, mihomo binary at $MIHOMO_BIN (or `mihomo` in PATH).

SOURCE=${1:-}
case "$SOURCE" in
  geoip)   SOURCE_BRANCH=sing-geoip; TARGET_BRANCH=mihomo-geoip; BEHAVIOR=ipcidr ;;
  geosite) SOURCE_BRANCH=sing-geosite; TARGET_BRANCH=mihomo-geosite; BEHAVIOR=domain ;;
  *) echo "usage: $0 <geoip|geosite>" >&2; exit 2 ;;
esac

ROOT=${GITHUB_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
ORIGIN="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}.git"
git -C "$ROOT" config http.https://github.com/.extraheader "AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GITHUB_TOKEN:?GITHUB_TOKEN is required}" | base64 -w0)"

git -C "$ROOT" fetch --no-tags --quiet origin "refs/heads/$SOURCE_BRANCH:refs/remotes/origin/$SOURCE_BRANCH"
mkdir -p "$WORK/source" "$WORK/output"
git -C "$ROOT" archive --format=tar "origin/$SOURCE_BRANCH" '*.json' | tar -xf - -C "$WORK/source"
json_count=$(find "$WORK/source" -maxdepth 1 -type f -name '*.json' | wc -l)
if ((json_count == 0)); then
  echo "no JSON artifacts on $SOURCE_BRANCH" >&2
  exit 1
fi

python3 "$ROOT/scripts/convert-mihomo-rules.py" "$WORK/source" "$WORK/output" "$BEHAVIOR" | tee "$WORK/convert.json"

# Compile every .yaml to .mrs with mihomo; a failing rule-set is fatal.
MIHOMO_BIN=${MIHOMO_BIN:-mihomo}
for yaml in "$WORK"/output/*.yaml; do
  "$MIHOMO_BIN" convert-ruleset "$BEHAVIOR" yaml "$yaml" "${yaml%.yaml}.mrs"
done

TARGET=$(mktemp -d)
trap 'rm -rf "$WORK" "$TARGET"' EXIT
TARGET_REF=$(git -C "$ROOT" ls-remote --heads origin "refs/heads/$TARGET_BRANCH") || {
  echo "unable to inspect $TARGET_BRANCH branch" >&2
  exit 1
}
if [[ -n "$TARGET_REF" ]]; then
  git clone --quiet --no-checkout "$ROOT" "$TARGET"
  git -C "$TARGET" remote set-url origin "$ORIGIN"
  git -C "$TARGET" config http.https://github.com/.extraheader "AUTHORIZATION: basic $(printf 'x-access-token:%s' "${GITHUB_TOKEN:?GITHUB_TOKEN is required}" | base64 -w0)"
  git -C "$TARGET" fetch --no-tags --quiet origin "refs/heads/$TARGET_BRANCH:refs/remotes/origin/$TARGET_BRANCH"
  git -C "$TARGET" checkout --quiet -B "$TARGET_BRANCH" "refs/remotes/origin/$TARGET_BRANCH"
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
git -C "$TARGET" commit --allow-empty --quiet -m "chore: sync $TARGET_BRANCH $(date -u +%F)"
git -C "$TARGET" push --quiet origin "HEAD:$TARGET_BRANCH"
printf 'branch=%s files=%s\n' "$TARGET_BRANCH" "$(find "$TARGET" -maxdepth 1 -type f | wc -l)"
