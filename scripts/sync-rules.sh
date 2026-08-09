#!/usr/bin/env bash
set -u -o pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VALIDATOR="$ROOT/scripts/validate-rule-json.py"
SOURCE=${1:-}

case "$SOURCE" in
  sing-geoip)
    REPOSITORY=SagerNet/sing-geoip
    PREFIX=geoip-
    ;;
  sing-geosite)
    REPOSITORY=SagerNet/sing-geosite
    PREFIX=geosite-
    ;;
  *)
    printf 'unknown source: %s\n' "$SOURCE" >&2
    exit 2
    ;;
esac

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SOURCE_DIR=${RULES_TEST_SOURCE_DIR:-}
TARGET_DIR=${RULES_TEST_TARGET_DIR:-}
SING_BOX=${SING_BOX_BIN:-sing-box}
FAILED="$WORK/failed.tsv"
SUCCESS="$WORK/success.tsv"
UPSTREAM="$WORK/upstream"
CURRENT="$WORK/current"
mkdir -p "$UPSTREAM" "$CURRENT"
: >"$FAILED"
: >"$SUCCESS"

sha256() { sha256sum "$1" | awk '{print $1}'; }

record_failure() {
  local file=$1 stage=$2 reason=$3 input_sha=${4:-} old_srs=${5:-} old_json=${6:-} blob=${7:-} size=${8:-} exit_code=${9:-}
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$file" "$stage" "$reason" "$input_sha" "$old_srs" "$old_json" "$blob" "$size" "$exit_code" >>"$FAILED"
  printf 'FAILED source=%s file=%s stage=%s reason=%s input_sha256=%s old_srs_sha256=%s old_json_sha256=%s git_blob_sha=%s size=%s exit_code=%s\n' \
    "$SOURCE" "$file" "$stage" "$reason" "$input_sha" "$old_srs" "$old_json" "$blob" "$size" "$exit_code" >&2
}

if [[ -n "$SOURCE_DIR" ]]; then
  cp -a "$SOURCE_DIR/." "$UPSTREAM/" || {
    printf 'failed to copy test source\n' >&2
    exit 1
  }
  SOURCE_COMMIT=${RULES_TEST_SOURCE_COMMIT:-test-source}
else
  SOURCE_COMMIT=$(git ls-remote "https://github.com/$REPOSITORY.git" "refs/heads/rule-set" | awk 'NR==1 {print $1}')
  if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'unable to resolve upstream commit for %s\n' "$REPOSITORY" >&2
    exit 1
  fi
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch rule-set \
    "https://github.com/$REPOSITORY.git" "$UPSTREAM" || {
    printf 'unable to clone upstream %s\n' "$REPOSITORY" >&2
    exit 1
  }
  ACTUAL=$(git -C "$UPSTREAM" rev-parse HEAD)
  if [[ "$ACTUAL" != "$SOURCE_COMMIT" ]]; then
    printf 'upstream moved during fetch: %s != %s\n' "$ACTUAL" "$SOURCE_COMMIT" >&2
    exit 1
  fi
fi

if [[ -n "$TARGET_DIR" ]]; then
  mkdir -p "$TARGET_DIR"
  find "$TARGET_DIR" -maxdepth 1 -type f \( -name "${PREFIX}*.srs" -o -name "${PREFIX}*.json" \) -exec cp -a {} "$CURRENT/" \; 2>/dev/null || true
else
  printf 'RULES_TEST_TARGET_DIR is required for local runs\n' >&2
  exit 1
fi

# Production callers provide a checked-out artifact branch directory. The test
# path above keeps the same merge semantics without contacting GitHub.

mapfile -t FILES < <(find "$UPSTREAM" -maxdepth 1 -type f -name "${PREFIX}*.srs" -printf '%f\n' | sort)
if ((${#FILES[@]} == 0)); then
  printf 'no upstream SRS files for %s\n' "$SOURCE" >&2
  exit 1
fi
declare -A UPSTREAM_FILES=()
for file in "${FILES[@]}"; do
  UPSTREAM_FILES["$file"]=1
done

for file in "${FILES[@]}"; do
  input="$UPSTREAM/$file"
  base=${file%.srs}
  output="$WORK/$base.json"
  roundtrip="$WORK/$base.roundtrip.srs"
  roundtrip_json="$WORK/$base.roundtrip.json"
  input_sha=$(sha256 "$input" 2>/dev/null || true)
  old_srs="$CURRENT/$file"
  old_json="$CURRENT/$base.json"
  old_srs_sha=
  old_json_sha=
  if [[ -f "$old_srs" ]]; then old_srs_sha=$(sha256 "$old_srs"); fi
  if [[ -f "$old_json" ]]; then old_json_sha=$(sha256 "$old_json"); fi
  blob_sha=$(git -C "$UPSTREAM" hash-object "$input" 2>/dev/null || true)
  input_size=$(wc -c <"$input" 2>/dev/null || printf '0')

  if [[ ! -f "$input" || -L "$input" || ! -s "$input" ]]; then
    record_failure "$file" input_validation "not a non-empty regular file" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" ""
    continue
  fi

  if ! "$SING_BOX" rule-set decompile "$input" --output "$output" >"$WORK/$base.stdout" 2>"$WORK/$base.stderr"; then
    record_failure "$file" srs_decompile "$(tr '\n' ' ' <"$WORK/$base.stderr" | cut -c1-1000)" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  if ! python3 "$VALIDATOR" validate "$output" 2>"$WORK/$base.validate"; then
    record_failure "$file" json_schema "$(tr '\n' ' ' <"$WORK/$base.validate" | cut -c1-1000)" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  if ! "$SING_BOX" rule-set compile "$output" --output "$roundtrip" >"$WORK/$base.compile.stdout" 2>"$WORK/$base.compile.stderr"; then
    record_failure "$file" roundtrip_compile "$(tr '\n' ' ' <"$WORK/$base.compile.stderr" | cut -c1-1000)" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  if ! "$SING_BOX" rule-set decompile "$roundtrip" --output "$roundtrip_json" >"$WORK/$base.roundtrip.stdout" 2>"$WORK/$base.roundtrip.stderr"; then
    record_failure "$file" roundtrip_decompile "$(tr '\n' ' ' <"$WORK/$base.roundtrip.stderr" | cut -c1-1000)" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  if ! python3 "$VALIDATOR" compare "$output" "$roundtrip_json" 2>"$WORK/$base.compare"; then
    record_failure "$file" roundtrip_compare "$(tr '\n' ' ' <"$WORK/$base.compare" | cut -c1-1000)" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi

  mkdir -p "$WORK/staged"
  staged_srs="$WORK/staged/$file.srs"
  staged_json="$WORK/staged/$base.json"
  if ! cp "$input" "$staged_srs"; then
    record_failure "$file" output_copy "unable to copy source SRS" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  if ! cp "$output" "$staged_json"; then
    record_failure "$file" output_copy "unable to copy generated JSON" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  if ! mv "$staged_srs" "$CURRENT/$file" || ! mv "$staged_json" "$CURRENT/$base.json"; then
    rm -f "$CURRENT/$file" "$CURRENT/$base.json" "$staged_srs" "$staged_json"
    record_failure "$file" output_copy "unable to install validated SRS and JSON pair" "$input_sha" "$old_srs_sha" "$old_json_sha" "$blob_sha" "$input_size" "1"
    continue
  fi
  printf '%s\t%s\t%s\n' "$file" "$input_sha" "$(sha256 "$output")" >>"$SUCCESS"
done

success_count=$(wc -l <"$SUCCESS")
failed_count=$(wc -l <"$FAILED")
retained_count=$(awk -F '\\t' '$5 != "" && $6 != "" {n++} END {print n+0}' "$FAILED")

# Remove only files confirmed absent from the pinned upstream tree. Failed files
# remain in CURRENT because they are still present in FILES.
for old in "$CURRENT"/"${PREFIX}"*.srs; do
  [[ -e "$old" ]] || continue
  old_name=$(basename "$old")
  if [[ -z "${UPSTREAM_FILES[$old_name]+x}" ]]; then
    rm -f "$CURRENT/$old_name" "$CURRENT/${old_name%.srs}.json"
  fi
done

while IFS=$'\t' read -r file input_sha output_sha; do
  [[ -n "$file" ]] || continue
  printf 'SUCCESS source=%s file=%s input_srs_sha256=%s output_json_sha256=%s\n' \
    "$SOURCE" "$file" "$input_sha" "$output_sha" >&2
done < "$SUCCESS"

final_srs_count=$(find "$CURRENT" -maxdepth 1 -type f -name "${PREFIX}*.srs" | wc -l)
final_json_count=$(find "$CURRENT" -maxdepth 1 -type f -name "${PREFIX}*.json" | wc -l)
if ((final_srs_count != success_count + retained_count || final_json_count != success_count + retained_count)); then
  printf 'final artifact count mismatch for %s: success=%s retained=%s srs=%s json=%s\n' \
    "$SOURCE" "$success_count" "$retained_count" "$final_srs_count" "$final_json_count" >&2
  exit 1
fi

find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -type f -delete
cp -a "$CURRENT/." "$TARGET_DIR/"
printf 'source=%s commit=%s successful=%s failed=%s target=%s\n' "$SOURCE" "$SOURCE_COMMIT" "$success_count" "$failed_count" "$TARGET_DIR"
if ((success_count == 0)); then
  printf 'no files succeeded for %s; existing artifacts retained\n' "$SOURCE" >&2
  exit 1
fi
if ((failed_count > 0)); then
  exit 3
fi
exit 0
