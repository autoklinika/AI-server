#!/usr/bin/env bash
set -Eeuo pipefail

STAGE="${1:-}"
[[ "$STAGE" =~ ^[EFGH]$ ]] || {
  echo "usage: $0 <E|F|G|H>" >&2
  exit 2
}

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || { echo "FAIL: run from AI-server repository"; exit 2; }

for cmd in git gh tmux flock; do
  command -v "$cmd" >/dev/null || { echo "FAIL: missing command: $cmd" >&2; exit 3; }
done
gh auth status >/dev/null 2>&1 || { echo "FAIL: gh auth missing" >&2; exit 3; }

CONTROL_DIR="$HOME/agent-control/stage-eh-master"
STATE_DIR="$HOME/agent-state/stage-eh"
WORKTREE="$HOME/agent-worktrees/stage-eh"
PRIVATE_ENV="$HOME/.config/ai-platform/autopilot.env"
SESSION="stage-eh-master"
STAGE_STATE="$STATE_DIR/stage-$STAGE"
status_file="$STAGE_STATE/status"

[[ -f "$PRIVATE_ENV" ]] || { echo "FAIL: autopilot private env missing"; exit 4; }
[[ -f "$status_file" ]] || { echo "FAIL: Stage $STAGE status missing"; exit 4; }
state="$(awk '{print $1}' "$status_file")"
[[ "$state" == "PRE_PROD_CI" ]] || {
  echo "FAIL: safe resume requires PRE_PROD_CI, got: $state"
  exit 5
}

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "FAIL: tmux session already exists: $SESSION"
  exit 6
fi

[[ -z "$(git -C "$WORKTREE" status --porcelain)" ]] || {
  echo "FAIL: Stage $STAGE worktree is dirty; refusing resume"
  exit 7
}

expected_branch="agent/stage-$(printf '%s' "$STAGE" | tr '[:upper:]' '[:lower:]')"
current_branch="$(git -C "$WORKTREE" branch --show-current)"
[[ "$current_branch" == "$expected_branch" ]] || {
  echo "FAIL: expected worktree branch $expected_branch, got: ${current_branch:-detached}"
  exit 8
}

# Refresh only the local control plane. The Stage candidate worktree is not reset.
mkdir -p "$CONTROL_DIR/prompts"
install -m 700 "$REPO_ROOT/deploy/autopilot/notify_telegram.py" "$CONTROL_DIR/notify_telegram.py"
install -m 700 "$REPO_ROOT/deploy/autopilot/run_stage.sh" "$CONTROL_DIR/run_stage.sh"
install -m 700 "$REPO_ROOT/deploy/autopilot/stage_eh_master.sh" "$CONTROL_DIR/master.sh"
install -m 600 "$REPO_ROOT"/deploy/autopilot/prompts/stage_*.md "$CONTROL_DIR/prompts/"

# The prior BLOCKED marker belongs to the already diagnosed PRE_PROD_CI race.
# Remove it only after all resume invariants above passed.
rm -f "$STATE_DIR/master.status"

launch="export PATH='$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin'; export AI_AUTOPILOT_ENV='$PRIVATE_ENV'; export AI_AUTOPILOT_CONTROL_DIR='$CONTROL_DIR'; export AI_AUTOPILOT_STATE_DIR='$STATE_DIR'; export AI_AUTOPILOT_WORKTREE='$WORKTREE'; export AI_AUTOPILOT_RESUME_STAGE='$STAGE'; exec '$CONTROL_DIR/master.sh' >> '$STATE_DIR/master-console.log' 2>&1"
tmux new-session -d -s "$SESSION" "$launch"

echo "RESUMED: Stage $STAGE from PRE_PROD_CI in tmux session $SESSION"
