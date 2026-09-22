#!/usr/bin/env bash
set -Eeuo pipefail

CONTROL_DIR="${AI_AUTOPILOT_CONTROL_DIR:-$HOME/agent-control/stage-eh-master}"
STATE_DIR="${AI_AUTOPILOT_STATE_DIR:-$HOME/agent-state/stage-eh}"
RUNNER="$CONTROL_DIR/run_stage.sh"
NOTIFY="$CONTROL_DIR/notify_telegram.py"

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/master.lock"
flock -n 9 || exit 0

notify() {
  "$NOTIFY" "$@" >/dev/null 2>&1 || true
}

unexpected_failure() {
  local rc=$?
  printf 'BLOCKED unexpected supervisor failure rc=%s at %s\n' "$rc" "$(date -Is)" > "$STATE_DIR/master.status"
  notify BLOCKED "E-H" "Supervisor zakończył się nieoczekiwanym błędem (rc=$rc). Produkcja nie będzie dalej zmieniana."
  exit "$rc"
}
trap unexpected_failure ERR

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
