#!/usr/bin/env bash
set -Eeuo pipefail

STAGE="${1:-}"
[[ "$STAGE" =~ ^[EFGH]$ ]] || { echo "usage: $0 <E|F|G|H>" >&2; exit 2; }
stage_lc="$(printf '%s' "$STAGE" | tr '[:upper:]' '[:lower:]')"

CONTROL_DIR="${AI_AUTOPILOT_CONTROL_DIR:-$HOME/agent-control/stage-eh-master}"
STATE_DIR="${AI_AUTOPILOT_STATE_DIR:-$HOME/agent-state/stage-eh}"
WORKTREE="${AI_AUTOPILOT_WORKTREE:-$HOME/agent-worktrees/stage-eh}"
NOTIFY="$CONTROL_DIR/notify_telegram.py"
SPEC="$CONTROL_DIR/prompts/stage_${stage_lc}.md"
BRANCH="agent/stage-${stage_lc}"
STAGE_STATE="$STATE_DIR/stage-$STAGE"
LOG_DIR="$STAGE_STATE/logs"
VENV="$STATE_DIR/venv"

mkdir -p "$LOG_DIR"
[[ -f "$SPEC" ]] || { echo "FAIL: stage spec missing: $SPEC" >&2; exit 3; }

notify() { "$NOTIFY" "$@" >/dev/null 2>&1 || true; }
set_state() { printf '%s %s\n' "$1" "$(date -Is)" > "$STAGE_STATE/status"; }

for cmd in git gh codex python3; do
  command -v "$cmd" >/dev/null || { echo "FAIL: missing command: $cmd" >&2; exit 3; }
done
gh auth status >/dev/null 2>&1 || { echo "FAIL: gh auth missing" >&2; exit 3; }

production_scripts() {
  local dir="$WORKTREE/deploy/stage-${stage_lc}/autopilot"
  for name in     00_preflight.sh 10_build_install.sh 20_cutover.sh 30_smoke.sh     40_rollback.sh 50_rollback_smoke.sh 60_reactivate.sh     70_reactivate_smoke.sh 90_finalize.sh
  do
    [[ -f "$dir/$name" ]] || return 1
    bash -n "$dir/$name" || return 1
  done
}

run_prod_step() {
  local name="$1"
  local path="$WORKTREE/deploy/stage-${stage_lc}/autopilot/$name"
  set_state "PRODUCTION:$name"
  (cd "$WORKTREE" && bash "$path") 2>&1 | tee "$LOG_DIR/$name.log"
}

emergency_rollback() {
  local why="$1"
  set +e
  set_state "EMERGENCY_ROLLBACK"
  notify ROLLBACK "$STAGE" "Wykryto błąd po rozpoczęciu zmian produkcyjnych: $why. Uruchamiam automatyczny rollback."
  (cd "$WORKTREE" && bash "deploy/stage-${stage_lc}/autopilot/40_rollback.sh")     >"$LOG_DIR/emergency-rollback.log" 2>&1
  rb=$?
  (cd "$WORKTREE" && bash "deploy/stage-${stage_lc}/autopilot/50_rollback_smoke.sh")     >"$LOG_DIR/emergency-rollback-smoke.log" 2>&1
  smoke=$?
  set -e
  if ((rb == 0 && smoke == 0)); then
    set_state "BLOCKED_ROLLED_BACK"
    notify BLOCKED "$STAGE" "Rollback zakończony PASS; poprzedni zweryfikowany release działa. Stage $STAGE zatrzymany."
  else
    set_state "BLOCKED_ROLLBACK_FAILED"
    notify BLOCKED "$STAGE" "KRYTYCZNE: automatyczny rollback lub jego smoke nie przeszedł. Stage zatrzymany."
  fi
  return 1
}

wait_main_ci() {
  local expected_sha="$1"
  local run_id=""
  for _ in $(seq 1 60); do
    row="$(gh run list --repo autoklinika/AI-server --workflow "AI Platform CI" --branch main       --limit 10 --json databaseId,headSha,status,conclusion       --jq ".[] | select(.headSha == \"$expected_sha\") | .databaseId" | head -n1 || true)"
    if [[ -n "$row" ]]; then run_id="$row"; break; fi
    sleep 5
  done
  [[ -n "$run_id" ]] || { echo "FAIL: post-merge CI run not found for $expected_sha"; return 1; }
  gh run watch "$run_id" --repo autoklinika/AI-server --exit-status
}

set_state PREFLIGHT
git -C "$WORKTREE" fetch origin main --prune
if [[ -n "$(git -C "$WORKTREE" status --porcelain)" ]]; then
  echo "FAIL: worktree dirty before Stage $STAGE" >&2
  exit 4
fi
git -C "$WORKTREE" checkout --detach origin/main
git -C "$WORKTREE" checkout -B "$BRANCH" origin/main

cat > "$STAGE_STATE/implement.prompt" <<EOF
You are the implementation agent for AI Platform Stage $STAGE.
Work only inside the current repository/worktree. Do not commit, push, create/merge PRs,
run gh, or change production. The supervisor owns all GitHub and production actions.

Read and obey:
- docs/architecture/AI_PLATFORM_MIGRATION_PLAN_V1_PL.md
- docs/architecture/AI_PLATFORM_TARGET_ARCHITECTURE_V1_PL.md
- docs/architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md
- $SPEC

Preserve all working Stage D behavior unless the Stage $STAGE specification explicitly
moves it behind a new boundary. Keep changes small, reversible and covered by tests.

MANDATORY AUTOPILOT CONTRACT:
Create deploy/stage-$stage_lc/autopilot/ with executable-compatible bash scripts:
00_preflight.sh       read-only production checks
10_build_install.sh   build/install candidate without activating it
20_cutover.sh         activate/mutate production
30_smoke.sh           real Stage $STAGE smoke/E2E
40_rollback.sh        restore the previous verified production state
50_rollback_smoke.sh  verify the restored state
60_reactivate.sh      re-activate the Stage $STAGE candidate
70_reactivate_smoke.sh verify final candidate state
90_finalize.sh        write/update the production gate report and repository evidence

Every mutating script must be idempotent or fail closed. Never destroy the rollback point.
Do not put secrets, prompts, tokens, chat IDs or private runtime content in reports/logs.
Stage H must quarantine before deletion and must preserve D.0/D.6 and the most recent
verified rollback releases required by the policy.

Run appropriate tests locally. When implementation and DEV gate are genuinely ready,
write exactly READY_FOR_REVIEW followed by a newline to:
.agent-result-stage-$stage_lc
Do not create that marker if anything remains knowingly broken.
EOF
cat "$SPEC" >> "$STAGE_STATE/implement.prompt"

set_state IMPLEMENT
(
  cd "$WORKTREE"
  codex --sandbox workspace-write --ask-for-approval never exec < "$STAGE_STATE/implement.prompt"
) 2>&1 | tee "$LOG_DIR/codex-implement.log"

marker="$WORKTREE/.agent-result-stage-$stage_lc"
[[ -f "$marker" ]] || { echo "FAIL: Codex result marker missing"; exit 5; }
[[ "$(tr -d '\r\n' < "$marker")" == "READY_FOR_REVIEW" ]] || { echo "FAIL: invalid Codex marker"; exit 5; }
rm -f "$marker"

set_state DEV_GATE
git -C "$WORKTREE" diff --check
find "$WORKTREE/deploy" -type f -name '*.sh' -print0 | sort -z | xargs -0 -n1 bash -n
production_scripts || { echo "FAIL: incomplete Stage $STAGE autopilot production contract"; exit 6; }

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --disable-pip-version-check -q -e "$WORKTREE[dev]"
(
  cd "$WORKTREE"
  "$VENV/bin/python" -m compileall -q src deploy/autopilot
  "$VENV/bin/python" -m pytest -q
) 2>&1 | tee "$LOG_DIR/dev-gate.log"

cat > "$STAGE_STATE/review.prompt" <<EOF
You are the independent production reviewer for AI Platform Stage $STAGE.
You are read-only. Inspect the current worktree diff against origin/main, tests,
Stage $STAGE production scripts and rollback design.

Read:
- docs/architecture/AI_PLATFORM_MIGRATION_PLAN_V1_PL.md
- docs/architecture/AI_PLATFORM_TARGET_ARCHITECTURE_V1_PL.md
- docs/architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md
- $SPEC

Reject if scope leaks into later stages, if rollback can lose the last verified state,
if secrets may leak, if smoke tests can pass without exercising the intended boundary,
or if a production mutation can occur before preflight/build have succeeded.

Your final line MUST be exactly one of:
AUTOPILOT_REVIEW=PASS
AUTOPILOT_REVIEW=BLOCKED
EOF
cat "$SPEC" >> "$STAGE_STATE/review.prompt"

set_state REVIEW
(
  cd "$WORKTREE"
  codex --sandbox read-only --ask-for-approval never exec < "$STAGE_STATE/review.prompt"
) 2>&1 | tee "$LOG_DIR/codex-review.log"

grep -qx 'AUTOPILOT_REVIEW=PASS' "$LOG_DIR/codex-review.log" || {
  set_state BLOCKED_REVIEW
  exit 7
}

set_state DEV_COMMIT
git -C "$WORKTREE" add -A
git -C "$WORKTREE" diff --cached --quiet && { echo "FAIL: no Stage $STAGE changes"; exit 8; }
git -C "$WORKTREE" commit -m "feat(stage-$stage_lc): implement autonomous Stage $STAGE candidate"
git -C "$WORKTREE" push -u origin "$BRANCH"

pr_url="$(cd "$WORKTREE" && gh pr create --repo autoklinika/AI-server --base main --head "$BRANCH"   --draft --title "Stage $STAGE: autonomous migration candidate"   --body "Autonomous Stage $STAGE candidate. Production gate is pending; do not merge until the supervisor records live smoke, rollback and reactivation evidence.")"
pr_number="$(printf '%s' "$pr_url" | sed -nE 's#.*/pull/([0-9]+).*#\1#p')"
[[ -n "$pr_number" ]] || { echo "FAIL: could not determine PR number"; exit 9; }

set_state PRE_PROD_CI
(cd "$WORKTREE" && gh pr checks "$pr_number" --repo autoklinika/AI-server --watch)

run_prod_step 00_preflight.sh
run_prod_step 10_build_install.sh

set_state PRODUCTION_MUTATING
if ! run_prod_step 20_cutover.sh; then emergency_rollback "cutover"; fi
if ! run_prod_step 30_smoke.sh; then emergency_rollback "live smoke/E2E"; fi

if ! run_prod_step 40_rollback.sh; then
  set_state BLOCKED_ROLLBACK_FAILED
  notify BLOCKED "$STAGE" "KRYTYCZNE: planowany test rollbacku nie wykonał się poprawnie."
  exit 10
fi
if ! run_prod_step 50_rollback_smoke.sh; then
  set_state BLOCKED_ROLLBACK_SMOKE_FAILED
  notify BLOCKED "$STAGE" "KRYTYCZNE: poprzedni release po rollbacku nie przeszedł smoke."
  exit 11
fi

if ! run_prod_step 60_reactivate.sh; then emergency_rollback "reactivation"; fi
if ! run_prod_step 70_reactivate_smoke.sh; then emergency_rollback "post-reactivation smoke"; fi
run_prod_step 90_finalize.sh

set_state FINAL_EVIDENCE
git -C "$WORKTREE" diff --check
git -C "$WORKTREE" add -A
if ! git -C "$WORKTREE" diff --cached --quiet; then
  git -C "$WORKTREE" commit -m "docs(stage-$stage_lc): record production validation"
  git -C "$WORKTREE" push
fi

set_state FINAL_CI
(cd "$WORKTREE" && gh pr checks "$pr_number" --repo autoklinika/AI-server --watch)
(cd "$WORKTREE" && gh pr ready "$pr_number" --repo autoklinika/AI-server)
(cd "$WORKTREE" && gh pr merge "$pr_number" --repo autoklinika/AI-server --merge --delete-branch)

set_state POST_MERGE_CI
git -C "$WORKTREE" fetch origin main --prune
main_sha="$(git -C "$WORKTREE" rev-parse origin/main)"
wait_main_ci "$main_sha"

git -C "$WORKTREE" checkout --detach origin/main
set_state COMPLETE
