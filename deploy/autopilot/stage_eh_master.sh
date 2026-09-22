#!/usr/bin/env bash
set -Eeuo pipefail

CONTROL_DIR="${AI_AUTOPILOT_CONTROL_DIR:-$HOME/agent-control/stage-eh-master}"
STATE_DIR="${AI_AUTOPILOT_STATE_DIR:-$HOME/agent-state/stage-eh}"
WORKTREE="${AI_AUTOPILOT_WORKTREE:-$HOME/agent-worktrees/stage-eh}"
RUNNER="$CONTROL_DIR/run_stage.sh"
NOTIFY="$CONTROL_DIR/notify_telegram.py"

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/master.lock"
flock -n 9 || exit 0

notify() {
  "$NOTIFY" "$@" >/dev/null 2>&1 || true
}

block_master() {
  local stage="$1" message="$2"
  printf 'BLOCKED stage=%s at=%s\n' "$stage" "$(date -Is)" > "$STATE_DIR/master.status"
  notify BLOCKED "$stage" "$message"
}

recover_interrupted_production() {
  local stage stage_lc status_file state rb smoke dir
  for stage in E F G H; do
    [[ -f "$STATE_DIR/stage-$stage.complete" ]] && continue
    status_file="$STATE_DIR/stage-$stage/status"
    [[ -f "$status_file" ]] || continue
    state="$(awk '{print $1}' "$status_file")"
    case "$state" in
      PRODUCTION_MUTATING|PRODUCTION:20_cutover.sh|PRODUCTION:30_smoke.sh|\
      PRODUCTION:40_rollback.sh|PRODUCTION:50_rollback_smoke.sh|\
      PRODUCTION:60_reactivate.sh|PRODUCTION:70_reactivate_smoke.sh|\
      PRODUCTION:90_finalize.sh|EMERGENCY_ROLLBACK)
        stage_lc="$(printf '%s' "$stage" | tr '[:upper:]' '[:lower:]')"
        dir="$WORKTREE/deploy/stage-$stage_lc/autopilot"
        notify ROLLBACK "$stage" "Wykryto przerwanie supervisora podczas fazy produkcyjnej. Wykonuję konserwatywny rollback przed zatrzymaniem."
        set +e
        (cd "$WORKTREE" && bash "$dir/40_rollback.sh") >"$STATE_DIR/stage-$stage/restart-rollback.log" 2>&1
        rb=$?
        (cd "$WORKTREE" && bash "$dir/50_rollback_smoke.sh") >"$STATE_DIR/stage-$stage/restart-rollback-smoke.log" 2>&1
        smoke=$?
        set -e
        if ((rb == 0 && smoke == 0)); then
          printf 'BLOCKED_ROLLED_BACK %s\n' "$(date -Is)" > "$status_file"
          block_master "$stage" "Supervisor został przerwany podczas produkcji. Rollback po restarcie: PASS; poprzedni zweryfikowany stan działa."
        else
          printf 'BLOCKED_ROLLBACK_FAILED %s\n' "$(date -Is)" > "$status_file"
          block_master "$stage" "KRYTYCZNE: supervisor został przerwany podczas produkcji, a rollback po restarcie nie przeszedł pełnego smoke."
        fi
        return 1
        ;;
    esac
  done
  return 0
}

unexpected_failure() {
  local rc=$?
  printf 'BLOCKED unexpected supervisor failure rc=%s at %s\n' "$rc" "$(date -Is)" > "$STATE_DIR/master.status"
  notify BLOCKED "E-H" "Supervisor zakończył się nieoczekiwanym błędem (rc=$rc). Produkcja nie będzie dalej zmieniana."
  exit "$rc"
}
trap unexpected_failure ERR

if [[ -f "$STATE_DIR/master.status" ]]; then
  previous="$(awk '{print $1}' "$STATE_DIR/master.status")"
  case "$previous" in
    COMPLETE|BLOCKED) exit 0 ;;
  esac
fi

if ! recover_interrupted_production; then
  exit 0
fi

# Any other stale per-stage state is intentionally fail-closed. A restart during
# implementation/CI must not reset or overwrite a branch automatically.
for stage in E F G H; do
  [[ -f "$STATE_DIR/stage-$stage.complete" ]] && continue
  status_file="$STATE_DIR/stage-$stage/status"
  if [[ -f "$status_file" ]]; then
    state="$(awk '{print $1}' "$status_file")"
    case "$state" in
      COMPLETE) ;;
      *)
        block_master "$stage" "Wykryto niedokończony stan '$state' po restarcie supervisora. Nie wykonuję automatycznie ponownie implementacji ani GitHub operations."
        exit 0
        ;;
    esac
  fi
done

printf 'RUNNING %s\n' "$(date -Is)" > "$STATE_DIR/master.status"

for stage in E F G H; do
  if [[ -f "$STATE_DIR/stage-$stage.complete" ]]; then
    continue
  fi

  notify STARTED "$stage" "Rozpoczynam autonomiczny Stage $stage."
  if "$RUNNER" "$stage"; then
    date -Is > "$STATE_DIR/stage-$stage.complete"
    notify COMPLETE "$stage" "Wdrożenie, smoke/E2E, test rollbacku, ponowna aktywacja, PR/CI/merge i post-merge CI: PASS."
  else
    rc=$?
    printf 'BLOCKED stage=%s rc=%s at=%s\n' "$stage" "$rc" "$(date -Is)" > "$STATE_DIR/master.status"
    notify BLOCKED "$stage" "Agent zatrzymany. Sprawdź raport/evidence Stage $stage; następny etap nie zostanie uruchomiony."
    exit 0
  fi
done

printf 'COMPLETE %s\n' "$(date -Is)" > "$STATE_DIR/master.status"
notify COMPLETE "E-H" "Stage E, F, G i H zakończone. Autonomiczna migracja core E-H: COMPLETE."
