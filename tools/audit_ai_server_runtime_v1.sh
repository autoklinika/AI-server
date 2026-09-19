#!/usr/bin/env bash
# AI Server runtime audit v1
# READ-ONLY: this script does not install, remove, restart, enable, disable,
# edit or write system configuration. It only prints diagnostic information.
set -uo pipefail

export LC_ALL=C

section() {
  printf '\n\n===== %s =====\n' "$1"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

run() {
  printf '\n$ %s\n' "$*"
  "$@" 2>&1 || printf '[command failed or unavailable: rc=%s]\n' "$?"
}

show_file_names_only() {
  local f="$1"
  [[ -r "$f" ]] || return 0
  printf '\n-- %s (VARIABLE NAMES ONLY) --\n' "$f"
  awk '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=/ {
      line=$0
      sub(/^[[:space:]]*/, "", line)
      split(line,a,"=")
      print a[1]"=<REDACTED>"
    }
  ' "$f"
}

git_audit() {
  local d="$1"
  [[ -d "$d/.git" || -f "$d/.git" ]] || return 0
  printf '\n-- GIT: %s --\n' "$d"
  git -C "$d" rev-parse --show-toplevel 2>/dev/null || true
  printf 'HEAD: '; git -C "$d" rev-parse HEAD 2>/dev/null || true
  printf 'BRANCH: '; git -C "$d" branch --show-current 2>/dev/null || true
  git -C "$d" status --short --branch 2>/dev/null || true
  printf 'WORKTREES:\n'
  git -C "$d" worktree list 2>/dev/null || true
}

systemd_summary() {
  local unit="$1"
  printf '\n-- %s --\n' "$unit"
  systemctl show "$unit"     -p Id -p LoadState -p ActiveState -p SubState -p UnitFileState     -p FragmentPath -p DropInPaths -p User -p Group -p ExecStart     --no-pager 2>/dev/null || true
}

user_systemd_summary() {
  local unit="$1"
  printf '\n-- user:%s --\n' "$unit"
  systemctl --user show "$unit"     -p Id -p LoadState -p ActiveState -p SubState -p UnitFileState     -p FragmentPath -p DropInPaths -p ExecStart     --no-pager 2>/dev/null || true
}

printf 'AI_SERVER_RUNTIME_AUDIT_VERSION=1\n'
printf 'READ_ONLY=true\n'
printf 'GENERATED_AT='; date --iso-8601=seconds 2>/dev/null || date
printf 'USER='; id -un 2>/dev/null || true
printf 'UID='; id -u 2>/dev/null || true

section "HOST / OS"
run hostnamectl
run uname -a
[[ -r /etc/os-release ]] && run cat /etc/os-release
if [[ -r /sys/class/dmi/id/sys_vendor ]]; then
  printf '\nDMI vendor: '; cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true
  printf 'DMI product: '; cat /sys/class/dmi/id/product_name 2>/dev/null || true
  printf 'DMI BIOS: '; cat /sys/class/dmi/id/bios_version 2>/dev/null || true
fi

section "CPU / MEMORY / GPU"
run lscpu
run free -h
grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo 2>/dev/null || true
have lspci && run bash -lc "lspci -nn | grep -Ei 'vga|3d|display|audio' || true"
have rocminfo && run bash -lc "rocminfo 2>/dev/null | grep -E 'Name:|Marketing Name:|gfx[0-9]+' | head -80"
have vulkaninfo && run bash -lc "vulkaninfo --summary 2>/dev/null | head -120"

section "STORAGE / MOUNTS"
run lsblk -o NAME,MODEL,SIZE,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS
run findmnt
run df -hT
printf '\n-- /etc/fstab (credentials path redacted if present) --\n'
if [[ -r /etc/fstab ]]; then
  sed -E 's/(credentials=)[^,[:space:]]+/\1<REDACTED>/g' /etc/fstab
fi

section "NETWORK"
run ip -brief address
run ip route
have ss && run ss -lntup
if have tailscale; then
  run tailscale version
  run tailscale status
fi

section "SYSTEMD - RELEVANT SYSTEM SERVICES"
for unit in   ollama.service   postgresql.service   docker.service   tailscaled.service   cockpit.socket   ai-bridge.service   ai-bridge-analysis.service   ai-bridge-analysis.timer   ai-gateway.service
do
  systemd_summary "$unit"
done
printf '\n-- FAILED SYSTEM UNITS --\n'
systemctl --failed --no-pager 2>/dev/null || true
printf '\n-- ACTIVE TIMERS --\n'
systemctl list-timers --all --no-pager 2>/dev/null || true
printf '\n-- ENABLED UNIT FILES (filtered) --\n'
systemctl list-unit-files --state=enabled --no-pager 2>/dev/null   | grep -Ei 'ai-|ollama|postgres|docker|tailscale|cockpit|hermes|comfy|telegram|discord' || true

section "SYSTEMD - USER SERVICES"
user_systemd_summary hermes-gateway.service
printf '\n-- ACTIVE USER SERVICES/TIMERS (filtered) --\n'
systemctl --user list-units --all --no-pager 2>/dev/null   | grep -Ei 'hermes|ai-|comfy|telegram|discord|voice|video|image' || true
systemctl --user list-timers --all --no-pager 2>/dev/null   | grep -Ei 'hermes|ai-|comfy|telegram|discord|voice|video|image' || true

section "CUSTOM SYSTEMD FILE INVENTORY"
find /etc/systemd/system -maxdepth 3 \( -type f -o -type l \) -printf '%p -> %l\n' 2>/dev/null   | grep -Ei 'ai-|ollama|hermes|comfy|telegram|discord|postgres|docker|tailscale' || true
find "$HOME/.config/systemd/user" -maxdepth 3 \( -type f -o -type l \) -printf '%p -> %l\n' 2>/dev/null   | grep -Ei 'ai-|ollama|hermes|comfy|telegram|discord' || true

section "CRON / SCHEDULED JOB INVENTORY"
printf '%s\n' '-- user crontab: schedules + command text with common secrets redacted --'
crontab -l 2>/dev/null   | sed -E       -e 's/([A-Za-z_]*(TOKEN|KEY|SECRET|PASSWORD|PASS)[A-Za-z_]*)=[^[:space:]]+/\1=<REDACTED>/Ig'       -e 's/(--(token|password|secret|api-key)[= ]+)[^[:space:]]+/\1<REDACTED>/Ig'   || true
printf '%s\n' '-- /etc/cron* filenames --'
find /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.weekly /etc/cron.monthly   -maxdepth 1 -type f -printf '%p\n' 2>/dev/null | sort || true

section "RUNNING PROCESSES - SAFE VIEW"
ps -eo pid,ppid,user,stat,comm --sort=user,pid 2>/dev/null   | grep -Ei 'PID|ollama|python|uvicorn|postgres|docker|container|hermes|comfy|tailscale|cockpit' || true

section "CONTAINERS"
if have docker; then
  run docker version
  printf '\n-- docker ps --\n'
  docker ps --no-trunc --format 'table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 || true
  printf '\n-- docker networks --\n'
  docker network ls 2>&1 || true
  printf '\n-- docker volumes --\n'
  docker volume ls 2>&1 || true
fi
if have podman; then
  run podman version
  run podman ps -a
fi

section "CORE TOOL VERSIONS"
have git && run git --version
have python3 && run python3 --version
have pip3 && run pip3 --version
have docker && run docker --version
have psql && run psql --version
have pg_isready && run pg_isready
have ollama && run ollama --version
have tailscale && run tailscale version

section "OLLAMA"
if have ollama; then
  run ollama list
  run ollama ps
fi
systemctl show ollama.service   -p FragmentPath -p DropInPaths -p ExecStart -p ActiveState -p UnitFileState   --no-pager 2>/dev/null || true
printf '\n-- Ollama drop-in filenames only --\n'
find /etc/systemd/system/ollama.service.d -maxdepth 1 -type f -printf '%p\n' 2>/dev/null | sort || true

section "AI-SERVER REPOSITORY"
git_audit "$HOME/AI-server"
if [[ -d "$HOME/AI-server" ]]; then
  printf '\n-- top-level repo entries --\n'
  find "$HOME/AI-server" -maxdepth 1 -mindepth 1 -printf '%f\n' 2>/dev/null | sort
fi

section "DEPLOYED AI SERVICES"
for d in /opt/ai-bridge /opt/ai-gateway; do
  if [[ -d "$d" ]]; then
    printf '\n-- %s --\n' "$d"
    ls -la "$d" 2>/dev/null | head -80
    [[ -x "$d/.venv/bin/python" ]] && "$d/.venv/bin/python" --version 2>&1 || true
    [[ -x "$d/.venv/bin/python" ]] && "$d/.venv/bin/python" -m pip show       fastapi httpx pydantic pydantic-settings sqlalchemy uvicorn alembic psycopg 2>/dev/null       | grep -E '^(Name|Version):' || true
  fi
done

section "HERMES"
HERMES_HOME="/srv/ai-data/hermes"
HERMES_REPO="$HERMES_HOME/hermes-agent"
if [[ -d "$HERMES_HOME" ]]; then
  printf '\n-- Hermes top-level files/dirs --\n'
  find "$HERMES_HOME" -maxdepth 1 -mindepth 1 -printf '%f\n' 2>/dev/null | sort
fi
git_audit "$HERMES_REPO"
if [[ -x "$HERMES_REPO/venv/bin/python" ]]; then
  "$HERMES_REPO/venv/bin/python" --version 2>&1 || true
fi

section "DATABASE / PERSISTENT DATA"
run bash -lc "ls -ld /var/lib/ai-bridge /var/lib/postgresql /srv/ai-data 2>/dev/null || true"
printf '\n-- first-level /srv/ai-data inventory --\n'
find /srv/ai-data -maxdepth 2 -mindepth 1 -printf '%y %p\n' 2>/dev/null | head -300 || true

section "CONFIGURATION INVENTORY - NO SECRET VALUES"
shopt -s nullglob
for f in /etc/ai-bridge/*.env /etc/ai-gateway/*.env; do
  show_file_names_only "$f"
done
printf '\n-- config filenames in relevant locations --\n'
find /etc/ai-bridge /etc/ai-gateway "$HERMES_HOME"   -maxdepth 2 -type f 2>/dev/null   | grep -Ei '\.(env|yaml|yml|toml|json|conf)$'   | sort   | head -300 || true

section "PERMISSIONS / OWNERSHIP"
for p in   "$HOME/AI-server"   /opt/ai-bridge   /opt/ai-gateway   /srv/ai-data   /srv/ai-data/hermes   /var/lib/ai-bridge   /etc/ai-bridge   /etc/ai-gateway
do
  [[ -e "$p" ]] && stat -c '%A %U:%G %a %n' "$p" 2>/dev/null || true
done

section "JOURNAL / FAILURES"
have journalctl && run journalctl --disk-usage
printf '\n-- failed unit names only --\n'
systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' || true

section "POTENTIAL WORKTREE / TEMPORARY CLUTTER"
printf '%s\n' '-- home directories matching known AI-server test/worktree patterns --'
find "$HOME" -maxdepth 1 -mindepth 1 -type d   \( -name 'AI-server-*' -o -name 'ai-server-*' -o -name '*stage*' -o -name '*validation*' -o -name '*test*' \)   -printf '%p\n' 2>/dev/null | sort || true
printf '%s\n' '-- /opt backup/stage directories --'
find /opt -maxdepth 1 -mindepth 1   \( -name 'ai-*.pre-*' -o -name '*stage*' -o -name '*.bak' -o -name '*backup*' \)   -printf '%p\n' 2>/dev/null | sort || true
printf '%s\n' '-- Hermes backup/stage files (names only) --'
find "$HERMES_HOME" -maxdepth 2 -type f   \( -name '*.bak' -o -name '*.backup' -o -name '*.pre-*' -o -name '*stage*' \)   -printf '%p\n' 2>/dev/null | sort | head -300 || true

section "AUDIT END"
printf 'READ_ONLY=true\n'
printf 'FINISHED_AT='; date --iso-8601=seconds 2>/dev/null || date
