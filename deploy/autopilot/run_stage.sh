#!/usr/bin/env bash
set -Eeuo pipefail

STAGE="${1:-}"
MODE="${2:-fresh}"
[[ "$STAGE" =~ ^[EFGH]$ ]] || { echo "usage: $0 <E|F|G|H> [--resume-pre-prod]" >&2; exit 2; }
[[ "$MODE" == "fresh" || "$MODE" == "--resume-pre-prod" ]] || {
  echo "usage: $0 <E|F|G|H> [--resume-pre-prod]" >&2
  exit 2
}
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
ROOT_BRIDGE="/usr/local/libexec/ai-platform/autopilot-root-exec"

mkdir -p "$LOG_DIR"
[[ -f "$SPEC" ]] || { echo "FAIL: stage spec missing: $SPEC" >&2; exit 3; }

notify() { "$NOTIFY" "$@" >/dev/null 2>&1 || true; }
set_state() { printf '%s %s\n' "$1" "$(date -Is)" > "$STAGE_STATE/status"; }

for cmd in git gh codex python3 sudo; do
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

root_bridge_ready() {
  [[ -x "$ROOT_BRIDGE" ]] || {
    echo "PRIVILEGE_BRIDGE=missing" >&2
    return 1
  }
  [[ "$(sudo -n "$ROOT_BRIDGE" --self-test 2>/dev/null || true)" == "AUTOPILOT_ROOT_BRIDGE=READY" ]] || {
    echo "PRIVILEGE_BRIDGE=not_authorized" >&2
    return 1
  }
}

run_root_step() {
  local name="$1"
  local expected_sha
  expected_sha="$(git -C "$WORKTREE" rev-parse HEAD)"
  sudo -n "$ROOT_BRIDGE" "$STAGE" "$name" "$expected_sha"
}

run_prod_step() {
  local name="$1"
  set_state "PRODUCTION:$name"
  run_root_step "$name" 2>&1 | tee "$LOG_DIR/$name.log"
}

emergency_rollback() {
  local why="$1"
  set +e
  set_state "EMERGENCY_ROLLBACK"
  notify ROLLBACK "$STAGE" "Wykryto błąd po rozpoczęciu zmian produkcyjnych: $why. Uruchamiam automatyczny rollback."
  run_root_step 40_rollback.sh >"$LOG_DIR/emergency-rollback.log" 2>&1
  rb=$?
  run_root_step 50_rollback_smoke.sh >"$LOG_DIR/emergency-rollback-smoke.log" 2>&1
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

wait_commit_ci() {
  local expected_sha="$1"
  local label="${2:-CI}"
  local run_id=""
  local row=""
  local snapshot=""
  local status=""
  local conclusion=""
  local observed_sha=""
  local transient_errors=0

  for _ in $(seq 1 180); do
    if row="$(gh run list --repo autoklinika/AI-server --workflow "AI Platform CI" \
      --limit 50 --json databaseId,headSha,status,conclusion,createdAt \
      --jq ".[] | select(.headSha == \"$expected_sha\") | [.databaseId,.createdAt] | join(\" \")" \
      2>/dev/null | head -n1)"; then
      if [[ -n "$row" ]]; then
        run_id="${row%% *}"
        break
      fi
    else
      transient_errors=$((transient_errors + 1))
    fi
    sleep 5
  done

  [[ -n "$run_id" ]] || {
    printf 'CI_GATE_TIMEOUT label=%s sha=%s transient_errors=%s\n' \
      "$label" "$expected_sha" "$transient_errors" >&2
    return 91
  }

  echo "CI_GATE label=$label sha=$expected_sha run_id=$run_id"

  for _ in $(seq 1 240); do
    if snapshot="$(gh run view "$run_id" --repo autoklinika/AI-server \
      --json status,conclusion,headSha \
      --jq '[.status,(.conclusion // "-"),.headSha] | join(" ")' 2>/dev/null)"; then
      read -r status conclusion observed_sha <<<"$snapshot"
      [[ "$observed_sha" == "$expected_sha" ]] || {
        echo "CI_GATE_SHA_MISMATCH expected=$expected_sha observed=$observed_sha" >&2
        return 92
      }
      case "$status" in
        completed)
          if [[ "$conclusion" == "success" ]]; then
            echo "CI_GATE_PASS label=$label run_id=$run_id"
            return 0
          fi
          echo "CI_GATE_FAIL label=$label run_id=$run_id conclusion=${conclusion:-unknown}" >&2
          return 93
          ;;
        queued|in_progress|requested|waiting|pending)
          ;;
        *)
          ;;
      esac
    else
      transient_errors=$((transient_errors + 1))
    fi
    sleep 5
  done

  printf 'CI_GATE_TIMEOUT label=%s run_id=%s transient_errors=%s\n' \
    "$label" "$run_id" "$transient_errors" >&2
  return 94
}

wait_main_ci() {
  local expected_sha="$1"
  wait_commit_ci "$expected_sha" "post-merge CI"
}

if [[ "$MODE" == "--resume-pre-prod" ]]; then
  previous_state="$(awk '{print $1}' "$STAGE_STATE/status" 2>/dev/null || true)"
  [[ "$previous_state" == "PRE_PROD_CI" ]] || {
    echo "FAIL: resume allowed only from PRE_PROD_CI, got: ${previous_state:-missing}"
    exit 20
  }
  [[ -z "$(git -C "$WORKTREE" status --porcelain)" ]] || {
    echo "FAIL: resume worktree is dirty"
    exit 21
  }

  git -C "$WORKTREE" fetch origin main "$BRANCH" --prune
  current_branch="$(git -C "$WORKTREE" branch --show-current)"
  [[ "$current_branch" == "$BRANCH" ]] || {
    echo "FAIL: resume requires branch $BRANCH, got: ${current_branch:-detached}"
    exit 22
  }

  # Accept reviewed remote repairs only by fast-forward; never overwrite local history.
  if [[ "$(git -C "$WORKTREE" rev-parse HEAD)" != "$(git -C "$WORKTREE" rev-parse "origin/$BRANCH")" ]]; then
    git -C "$WORKTREE" merge --ff-only "origin/$BRANCH"
  fi

  # Branch protection requires the candidate to contain current main. Updating here
  # is safe because production has not been touched yet; any conflict fails closed.
  if ! git -C "$WORKTREE" merge-base --is-ancestor origin/main HEAD; then
    git -C "$WORKTREE" merge --no-edit origin/main
    git -C "$WORKTREE" push origin "$BRANCH"
  fi

  head_sha="$(git -C "$WORKTREE" rev-parse HEAD)"
  remote_sha="$(git -C "$WORKTREE" rev-parse "origin/$BRANCH")"
  [[ "$head_sha" == "$remote_sha" ]] || {
    echo "FAIL: local/remote Stage $STAGE branch mismatch after update"
    exit 23
  }

  pr_number="$(cd "$WORKTREE" && gh pr view "$BRANCH" --repo autoklinika/AI-server \
    --json number,baseRefName,state \
    --jq 'select(.baseRefName == "main" and .state == "OPEN") | .number')"
  [[ -n "$pr_number" ]] || {
    echo "FAIL: open PR to main not found for $BRANCH"
    exit 24
  }

  set_state DEV_GATE
  git -C "$WORKTREE" diff --check
  find "$WORKTREE/deploy" -type f -name '*.sh' -print0 | sort -z | xargs -0 -n1 bash -n
  production_scripts || { echo "FAIL: incomplete Stage $STAGE autopilot production contract"; exit 25; }
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q -e "$WORKTREE[dev]"
  (
    cd "$WORKTREE"
    "$VENV/bin/python" -m compileall -q src deploy/autopilot
    "$VENV/bin/python" -m pytest -q
  ) 2>&1 | tee "$LOG_DIR/resume-dev-gate.log"

  set_state REVIEW
  (
    cd "$WORKTREE"
    codex --sandbox read-only --ask-for-approval never exec < "$STAGE_STATE/review.prompt"
  ) 2>&1 | tee "$LOG_DIR/codex-review-resume.log"
  grep -qx 'AUTOPILOT_REVIEW=PASS' "$LOG_DIR/codex-review-resume.log" || {
    set_state BLOCKED_REVIEW
    exit 26
  }
else
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
Production scripts are executed as root by a root-owned privilege bridge with a minimal
environment. They must not prompt for sudo, depend on an interactive shell, or require
unversioned environment variables. The bridge verifies clean tracked bytes and exact SHA.
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

fi

set_state PRE_PROD_CI
candidate_sha="$(git -C "$WORKTREE" rev-parse HEAD)"
wait_commit_ci "$candidate_sha" "pre-production CI"

if ! root_bridge_ready; then
  printf 'PRIVILEGE_BRIDGE_REQUIRED\n' > "$STAGE_STATE/reason"
  exit 30
fi

preflight_ok=0
for attempt in 1 2 3; do
  if run_prod_step 00_preflight.sh; then
    preflight_ok=1
    break
  fi
  set_state PRE_PROD_CI
  reason="$(grep -E '^(PREFLIGHT_FAIL|AUTOPILOT_ROOT_DENY)=' "$LOG_DIR/00_preflight.sh.log" 2>/dev/null | tail -n1 || true)"
  [[ -n "$reason" ]] && printf '%s\n' "$reason" > "$STAGE_STATE/reason"
  if ((attempt < 3)); then
    sleep 20
  fi
done
if ((preflight_ok == 0)); then
  set_state PRE_PROD_CI
  exit 31
fi
rm -f "$STAGE_STATE/reason"
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
final_sha="$(git -C "$WORKTREE" rev-parse HEAD)"
wait_commit_ci "$final_sha" "final PR CI"
(cd "$WORKTREE" && gh pr ready "$pr_number" --repo autoklinika/AI-server)
(cd "$WORKTREE" && gh pr merge "$pr_number" --repo autoklinika/AI-server --merge --delete-branch)

set_state POST_MERGE_CI
git -C "$WORKTREE" fetch origin main --prune
main_sha="$(git -C "$WORKTREE" rev-parse origin/main)"
wait_main_ci "$main_sha"

git -C "$WORKTREE" checkout --detach origin/main
set_state COMPLETE
