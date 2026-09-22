#!/usr/bin/env bash
set -Eeuo pipefail

# Installed copy is rendered by install_privilege_bridge.sh. The placeholders
# intentionally make the repository copy non-operational as a privileged helper.
ALLOWED_USER="__AUTOPILOT_USER__"
ALLOWED_UID="__AUTOPILOT_UID__"
ALLOWED_HOME="__AUTOPILOT_HOME__"
WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-eh"

fail() {
  printf 'AUTOPILOT_ROOT_DENY=%s\n' "$1" >&2
  exit 64
}

[[ "$ALLOWED_USER" != __AUTOPILOT_* ]] || fail "unrendered_helper"
[[ "$ALLOWED_UID" =~ ^[0-9]+$ ]] || fail "invalid_installed_uid"
[[ "$ALLOWED_HOME" == /* ]] || fail "invalid_installed_home"

caller="${SUDO_USER:-}"
caller_uid="${SUDO_UID:-}"
[[ "$caller" == "$ALLOWED_USER" ]] || fail "caller"
[[ "$caller_uid" == "$ALLOWED_UID" ]] || fail "caller_uid"

if [[ "${1:-}" == "--self-test" && $# -eq 1 ]]; then
  printf 'AUTOPILOT_ROOT_BRIDGE=READY\n'
  exit 0
fi

[[ $# -eq 3 ]] || fail "arguments"
stage="$1"
step="$2"
expected_sha="$3"

[[ "$stage" =~ ^[EFGH]$ ]] || fail "stage"
case "$step" in
  00_preflight.sh|10_build_install.sh|20_cutover.sh|30_smoke.sh|40_rollback.sh|  50_rollback_smoke.sh|60_reactivate.sh|70_reactivate_smoke.sh|90_finalize.sh)
    ;;
  *) fail "step" ;;
esac
[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || fail "sha"

[[ -e "$WORKTREE/.git" ]] || fail "worktree"
owner_uid="$(stat -c '%u' "$WORKTREE")"
[[ "$owner_uid" == "$ALLOWED_UID" ]] || fail "worktree_owner"

stage_lc="$(printf '%s' "$stage" | tr '[:upper:]' '[:lower:]')"
expected_branch="agent/stage-$stage_lc"

head_sha="$(git -C "$WORKTREE" rev-parse HEAD 2>/dev/null || true)"
[[ "$head_sha" == "$expected_sha" ]] || fail "head_sha"
branch="$(git -C "$WORKTREE" branch --show-current 2>/dev/null || true)"
[[ "$branch" == "$expected_branch" ]] || fail "branch"

[[ -z "$(git -C "$WORKTREE" status --porcelain --untracked-files=all)" ]] || fail "dirty"

remote_sha="$(git -C "$WORKTREE" rev-parse "refs/remotes/origin/$expected_branch" 2>/dev/null || true)"
[[ "$remote_sha" == "$expected_sha" ]] || fail "remote_sha"
git -C "$WORKTREE" merge-base --is-ancestor origin/main "$expected_sha" >/dev/null 2>&1   || fail "main_ancestor"

relative="deploy/stage-$stage_lc/autopilot/$step"
script="$WORKTREE/$relative"
git -C "$WORKTREE" ls-files --error-unmatch "$relative" >/dev/null 2>&1 || fail "untracked_step"
[[ -f "$script" && ! -L "$script" ]] || fail "step_file"
[[ "$(stat -c '%u' "$script")" == "$ALLOWED_UID" ]] || fail "step_owner"

# Confirm working-tree bytes match the committed object independently of status.
committed_hash="$(git -C "$WORKTREE" show "$expected_sha:$relative" | sha256sum | awk '{print $1}')"
working_hash="$(sha256sum "$script" | awk '{print $1}')"
[[ "$committed_hash" == "$working_hash" ]] || fail "step_hash"

cd "$WORKTREE"
exec env -i   HOME="$ALLOWED_HOME"   PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"   LANG="C.UTF-8"   USER="root"   LOGNAME="root"   bash "$script"
