#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${1:?usage: $0 SOURCE_DIR RELEASE_ID}"
RELEASE_ID="${2:?usage: $0 SOURCE_DIR RELEASE_ID}"
TARGET="/opt/ai-platform/releases/$RELEASE_ID"
CURRENT="/opt/ai-platform/current"
PYTHON_BIN="${PYTHON_BIN:-python3.14}"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -d "$SOURCE_DIR" ]] || fail "source release missing: $SOURCE_DIR"
[[ -f "$SOURCE_DIR/RELEASE" ]] || fail "source RELEASE stamp missing"
[[ -f "$SOURCE_DIR/metadata/SHA256SUMS" ]] || fail "source checksums missing"
grep -qx "release_id=$RELEASE_ID" "$SOURCE_DIR/RELEASE"   || fail "source release id does not match argument"
grep -qx 'stage=D' "$SOURCE_DIR/RELEASE"   || fail "source is not a Stage D release"

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

echo "===== INSTALL RELEASE SOURCE WITHOUT ACTIVATION ====="
sudo install -d -m 0755 "$TARGET"

# Python virtual environments are not relocatable: console-script shebangs
# contain the absolute interpreter path. Copy source/metadata but deliberately
# rebuild both venvs in their final /opt paths.
tar   --exclude='./services/ai-bridge/.venv'   --exclude='./services/ai-gateway/.venv'   --exclude='./metadata/SHA256SUMS'   -C "$SOURCE_DIR" -cf - .   | sudo tar -C "$TARGET" -xf -

echo "===== BUILD FINAL-PATH AI BRIDGE VENV ====="
sudo "$PYTHON_BIN" -m venv "$TARGET/services/ai-bridge/.venv"
sudo "$TARGET/services/ai-bridge/.venv/bin/python" -m pip   --disable-pip-version-check install   -r "$TARGET/metadata/locks/ai-bridge.requirements.txt"
sudo "$TARGET/services/ai-bridge/.venv/bin/python" -m pip   --disable-pip-version-check install   --no-deps "$TARGET/services/ai-bridge"

echo "===== BUILD FINAL-PATH AI GATEWAY VENV ====="
sudo "$PYTHON_BIN" -m venv "$TARGET/services/ai-gateway/.venv"
sudo "$TARGET/services/ai-gateway/.venv/bin/python" -m pip   --disable-pip-version-check install   -r "$TARGET/metadata/locks/ai-gateway.requirements.txt"
sudo "$TARGET/services/ai-gateway/.venv/bin/python" -m pip   --disable-pip-version-check install   --no-deps "$TARGET/services/ai-gateway"

echo "===== VERIFY FINAL-PATH ENTRYPOINTS ====="
BRIDGE_ENTRY="$TARGET/services/ai-bridge/.venv/bin/ai-bridge"
ANALYSIS_ENTRY="$TARGET/services/ai-bridge/.venv/bin/ai-bridge-analyze-ventilation"
[[ -x "$BRIDGE_ENTRY" ]] || fail "AI Bridge entrypoint missing"
[[ -x "$ANALYSIS_ENTRY" ]] || fail "AI analysis entrypoint missing"

BRIDGE_SHEBANG="$(head -1 "$BRIDGE_ENTRY")"
ANALYSIS_SHEBANG="$(head -1 "$ANALYSIS_ENTRY")"
[[ "$BRIDGE_SHEBANG" == "#!$TARGET/services/ai-bridge/.venv/bin/python"* ]]   || fail "AI Bridge entrypoint points outside final release: $BRIDGE_SHEBANG"
[[ "$ANALYSIS_SHEBANG" == "#!$TARGET/services/ai-bridge/.venv/bin/python"* ]]   || fail "AI analysis entrypoint points outside final release: $ANALYSIS_SHEBANG"
[[ "$BRIDGE_SHEBANG" != *"/tmp/"* ]] || fail "AI Bridge entrypoint still references /tmp"
[[ "$ANALYSIS_SHEBANG" != *"/tmp/"* ]] || fail "AI analysis entrypoint still references /tmp"
say "PASS: final-path entrypoint shebangs"

echo "===== WRITE INSTALLED CHECKSUMS ====="
CHECKSUM_TMP="$(mktemp)"
trap 'rm -f "$CHECKSUM_TMP"' EXIT
(
  cd "$TARGET"
  find . -type f ! -path './metadata/SHA256SUMS' -print0     | sort -z     | xargs -0 sha256sum     > "$CHECKSUM_TMP"
)
sudo install -m 0644 "$CHECKSUM_TMP" "$TARGET/metadata/SHA256SUMS"
rm -f "$CHECKSUM_TMP"
trap - EXIT

(
  cd "$TARGET"
  sudo sha256sum -c metadata/SHA256SUMS >/dev/null
) || {
  sudo rm -rf "$TARGET"
  fail "installed release checksum validation failed"
}
say "PASS: installed release checksums"

[[ "$(readlink -f "$CURRENT")" == "$CURRENT_BEFORE" ]]   || fail "current release changed during install"

echo "INSTALL STAGE D RELEASE: PASS"
say "installed=$TARGET"
say "current_unchanged=$CURRENT_BEFORE"
