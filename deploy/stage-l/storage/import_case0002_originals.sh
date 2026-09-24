#!/usr/bin/env bash
set -Eeuo pipefail

DEST="/srv/ai-data/knowledge/source-cache/EcuRepairService/cases/CASE-0002-SCANIA-EMS-S6-DC1210-ECU-CLONE/local-originals"
MANIFEST="$DEST/EXPECTED_SHA256SUMS.txt"
EXPECTED_ZIP_SHA256="36d42e2899b10914c35db9de86fe0012becd2a4ce6d57b1718f9d8981e6d7bba"

fail() {
  printf 'CASE0002_IMPORT_FAIL=%s\n' "$1" >&2
  exit 64
}

[[ $# -eq 1 ]] || fail "usage_zip_path"
ZIP="$(readlink -f "$1")"
[[ -f "$ZIP" ]] || fail "zip_missing"
[[ -f "$MANIFEST" ]] || fail "expected_manifest_missing"
command -v unzip >/dev/null || fail "unzip_missing"

actual_zip_sha="$(sha256sum "$ZIP" | awk '{print $1}')"
[[ "$actual_zip_sha" == "$EXPECTED_ZIP_SHA256" ]] || fail "zip_sha256_mismatch"

expected_count="$(grep -Ec '^[0-9a-f]{64}  .+' "$MANIFEST")"
[[ "$expected_count" -eq 11 ]] || fail "unexpected_manifest_count"

STAGING="$(mktemp -d "$DEST/.import.XXXXXX")"
cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT
unzip -q "$ZIP" -d "$STAGING"

# Verify the 11 originals against the server-side expected manifest.
(
  cd "$STAGING"
  sha256sum -c "$MANIFEST"
) || fail "artifact_sha256_verification"

actual_payload_count="$(
  find "$STAGING" -maxdepth 1 -type f ! -name EXPECTED_SHA256SUMS.txt -printf '%f\n' | wc -l
)"
[[ "$actual_payload_count" -eq 11 ]] || fail "unexpected_payload_count"

while IFS= read -r line; do
  [[ "$line" =~ ^[0-9a-f]{64}[[:space:]][[:space:]] ]] || continue
  digest="${line:0:64}"
  name="${line:66}"
  source="$STAGING/$name"
  target="$DEST/$name"

  [[ -f "$source" ]] || fail "verified_file_missing"
  if [[ -f "$target" ]]; then
    existing="$(sha256sum "$target" | awk '{print $1}')"
    [[ "$existing" == "$digest" ]] || fail "existing_target_hash_mismatch"
    continue
  fi

  tmp="$DEST/.$(basename "$name").tmp.$$"
  cp -- "$source" "$tmp"
  [[ "$(sha256sum "$tmp" | awk '{print $1}')" == "$digest" ]] || fail "copy_hash_mismatch"
  chmod 0440 "$tmp"
  mv "$tmp" "$target"
done < "$MANIFEST"
(
  cd "$DEST"
  sha256sum -c EXPECTED_SHA256SUMS.txt
) >/dev/null || fail "final_verification"

stored_count="$(
  find "$DEST" -maxdepth 1 -type f ! -name EXPECTED_SHA256SUMS.txt ! -name README_LOCAL.txt -printf '%f\n' | wc -l
)"
[[ "$stored_count" -eq 11 ]] || fail "final_file_count"

printf 'CASE0002_IMPORT=PASS\n'
printf 'ZIP_SHA256=%s\n' "$actual_zip_sha"
printf 'ARTIFACTS=%s\n' "$stored_count"
printf 'DEST=%s\n' "$DEST"
printf 'NEXT=run Stage K K3 backup and restore validation before deleting source ZIP\n'
