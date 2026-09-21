#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${1:?usage: $0 SOURCE_DIR RELEASE_ID}"
RELEASE_ID="${2:?usage: $0 SOURCE_DIR RELEASE_ID}"
TARGET="/opt/ai-platform/releases/$RELEASE_ID"
CURRENT="/opt/ai-platform/current"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -d "$SOURCE_DIR" ]] || fail "source release missing: $SOURCE_DIR"
[[ -f "$SOURCE_DIR/RELEASE" ]] || fail "source RELEASE stamp missing"
[[ -f "$SOURCE_DIR/metadata/SHA256SUMS" ]] || fail "source checksums missing"
grep -qx "release_id=$RELEASE_ID" "$SOURCE_DIR/RELEASE"   || fail "source release id does not match argument"
grep -qx 'stage=C' "$SOURCE_DIR/RELEASE"   || fail "source is not a Stage C release"

(
  cd "$SOURCE_DIR"
  sha256sum -c metadata/SHA256SUMS >/dev/null
) || fail "source release checksum validation failed"
say "PASS: source release checksums"

CURRENT_BEFORE="$(readlink -f "$CURRENT" 2>/dev/null || true)"
[[ -n "$CURRENT_BEFORE" && -d "$CURRENT_BEFORE" ]]   || fail "current production release symlink is invalid"

if sudo test -e "$TARGET"; then
  fail "target release already exists: $TARGET"
fi

echo "===== INSTALL RELEASE WITHOUT ACTIVATION ====="
sudo install -d -m 0755 /opt/ai-platform/releases
sudo cp -a "$SOURCE_DIR" "$TARGET"

(
  cd "$TARGET"
  sudo sha256sum -c metadata/SHA256SUMS >/dev/null
) || {
  sudo rm -rf "$TARGET"
  fail "installed release checksum validation failed"
}
say "PASS: installed release checksums"

[[ "$(readlink -f "$CURRENT")" == "$CURRENT_BEFORE" ]]   || fail "current release changed during install"

echo "INSTALL STAGE C RELEASE: PASS"
say "installed=$TARGET"
say "current_unchanged=$CURRENT_BEFORE"
