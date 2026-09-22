#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || { echo "FAIL: run from AI-server repository" >&2; exit 2; }

for cmd in sudo install sed visudo mktemp getent; do
  command -v "$cmd" >/dev/null || { echo "FAIL: missing command: $cmd" >&2; exit 3; }
done

user_name="$(id -un)"
user_uid="$(id -u)"
user_home="$(getent passwd "$user_name" | cut -d: -f6)"
[[ "$user_name" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "FAIL: unsafe username"; exit 4; }
[[ "$user_uid" =~ ^[0-9]+$ ]] || { echo "FAIL: invalid uid"; exit 4; }
[[ "$user_home" == /* && -d "$user_home" ]] || { echo "FAIL: invalid home"; exit 4; }

source_helper="$REPO_ROOT/deploy/autopilot/root_executor.sh"
[[ -f "$source_helper" ]] || { echo "FAIL: helper source missing"; exit 5; }
bash -n "$source_helper"

tmp="$(mktemp)"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

escape_sed() { printf '%s' "$1" | sed 's/[&|\\]/\\&/g'; }
safe_user="$(escape_sed "$user_name")"
safe_uid="$(escape_sed "$user_uid")"
safe_home="$(escape_sed "$user_home")"

sed   -e "s|__AUTOPILOT_USER__|$safe_user|g"   -e "s|__AUTOPILOT_UID__|$safe_uid|g"   -e "s|__AUTOPILOT_HOME__|$safe_home|g"   "$source_helper" > "$tmp"
bash -n "$tmp"

helper_dst="/usr/local/libexec/ai-platform/autopilot-root-exec"
sudoers_dst="/etc/sudoers.d/ai-platform-autopilot"

echo "Installing one-time AI Platform privilege bridge (sudo password may be requested)..."
sudo install -d -o root -g root -m 0755 /usr/local/libexec/ai-platform
sudo install -o root -g root -m 0755 "$tmp" "$helper_dst"

sudo_tmp="$(mktemp)"
trap 'cleanup; rm -f "$sudo_tmp"' EXIT
printf '%s ALL=(root) NOPASSWD: %s *\n' "$user_name" "$helper_dst" > "$sudo_tmp"
chmod 0600 "$sudo_tmp"
sudo visudo -cf "$sudo_tmp" >/dev/null
sudo install -o root -g root -m 0440 "$sudo_tmp" "$sudoers_dst"
sudo visudo -cf "$sudoers_dst" >/dev/null

result="$(sudo -n "$helper_dst" --self-test)"
[[ "$result" == "AUTOPILOT_ROOT_BRIDGE=READY" ]] || {
  echo "FAIL: privilege bridge self-test failed" >&2
  exit 6
}

echo "PASS: AI Platform privilege bridge installed for $user_name"
echo "The bridge grants no general shell; it accepts only Stage E-H production step names."
