#!/usr/bin/env bash
# AI Server runtime audit v1.1 supplemental collector
# READ-ONLY. No install/restart/remove/write operations.
set -uo pipefail
export LC_ALL=C

section(){ printf '\n\n===== %s =====\n' "$1"; }
safe_show(){
  local unit="$1"
  printf '\n-- %s --\n' "$unit"
  systemctl show "$unit"     -p Id -p LoadState -p ActiveState -p SubState -p UnitFileState     -p FragmentPath -p DropInPaths -p User -p Group -p WorkingDirectory -p ExecStart     --no-pager 2>/dev/null || true
}

printf 'AI_SERVER_RUNTIME_AUDIT_VERSION=1.1\n'
printf 'READ_ONLY=true\n'
printf 'GENERATED_AT='; date --iso-8601=seconds 2>/dev/null || date

section "SUPPLEMENTAL SYSTEMD"
safe_show comfyui.service
safe_show ollama-preload.service
safe_show ollama.service
safe_show ai-bridge.service
safe_show ai-bridge-analysis.service
safe_show ai-gateway.service

printf '\n-- custom unit/drop-in metadata and hashes --\n'
for f in   /etc/systemd/system/comfyui.service   /etc/systemd/system/ollama-preload.service   /etc/systemd/system/ollama.service   /etc/systemd/system/ollama.service.d/*.conf   /etc/systemd/system/ai-bridge.service   /etc/systemd/system/ai-bridge.service.d/*.conf   /etc/systemd/system/ai-bridge-analysis.service   /etc/systemd/system/ai-bridge-analysis.service.d/*.conf   /etc/systemd/system/ai-gateway.service
do
  [[ -f "$f" ]] || continue
  stat -c '%A %U:%G %a %s %y %n' "$f" 2>/dev/null || true
  sha256sum "$f" 2>/dev/null || true
done

section "FIREWALL / PACKET FILTER"
if command -v ufw >/dev/null 2>&1; then
  ufw status verbose 2>&1 || sudo -n ufw status verbose 2>&1 || true
fi
if command -v nft >/dev/null 2>&1; then
  printf '\n-- nft ruleset summary (if readable without interactive sudo) --\n'
  nft list ruleset 2>&1 | head -250 || sudo -n nft list ruleset 2>&1 | head -250 || true
fi

section "STORAGE USAGE"
for p in   /srv/ai-data   /srv/ai-data/hermes   /srv/ai-data/hermes-video-jobs   /srv/ai-data/hermes-foto-jobs   /srv/ai-data/hermes-media   /srv/ai-data/comfyui-data   /srv/ai-data/comfyui-output   /var/lib/ai-bridge   /opt/ai-bridge   /opt/ai-gateway   /opt/ai-gateway.pre-stage2   /opt/ai-gateway.pre-stage3
do
  [[ -e "$p" ]] && du -sh "$p" 2>/dev/null || true
done

printf '\n-- Ollama storage candidates --\n'
for p in /usr/share/ollama /var/lib/ollama /home/ollama/.ollama "$HOME/.ollama"; do
  [[ -e "$p" ]] && du -sh "$p" 2>/dev/null || true
done

section "AI BRIDGE DATABASE - SAFE METADATA"
if [[ -r /etc/ai-bridge/ai-bridge.env && -x /opt/ai-bridge/.venv/bin/python ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/ai-bridge/ai-bridge.env >/dev/null 2>&1 || true
  set +a
  /opt/ai-bridge/.venv/bin/python - <<'PY' 2>&1 || true
import os
from sqlalchemy import create_engine, text
url=os.environ.get("AI_BRIDGE_DATABASE_URL")
if not url:
    print("database_url: unavailable")
    raise SystemExit(0)
engine=create_engine(url)
with engine.connect() as c:
    print("database:", c.execute(text("select current_database()")).scalar())
    print("server_version:", c.execute(text("show server_version")).scalar())
    print("database_size_bytes:", c.execute(text("select pg_database_size(current_database())")).scalar())
    rows=c.execute(text("""
      select schemaname, relname, n_live_tup
      from pg_stat_user_tables
      order by schemaname, relname
    """)).all()
    print("user_tables:")
    for schema, name, approx in rows:
        print(f"  {schema}.{name} approx_rows={approx}")
PY
  unset AI_BRIDGE_DATABASE_URL
else
  echo "database metadata skipped: env/python unavailable"
fi

section "HERMES GIT DRIFT"
HERMES=/srv/ai-data/hermes/hermes-agent
if [[ -d "$HERMES/.git" ]]; then
  git -C "$HERMES" status --short --branch 2>/dev/null || true
  printf '\n-- diff stat --\n'
  git -C "$HERMES" diff --stat 2>/dev/null || true
  printf '\n-- changed file hashes --\n'
  for f in agent/turn_api_request.py gateway/run_inbound.py gateway/run_turn_runner.py; do
    [[ -f "$HERMES/$f" ]] && sha256sum "$HERMES/$f" || true
  done
  printf '\n-- local commits not in origin/main (metadata only) --\n'
  git -C "$HERMES" log --oneline --decorate origin/main..HEAD 2>/dev/null | head -30 || true
  printf '\n-- origin commits not in local HEAD (metadata only) --\n'
  git -C "$HERMES" log --oneline --decorate HEAD..origin/main 2>/dev/null | head -30 || true
fi

section "PRODUCTION HELPER INVENTORY"
printf '%s\n' '-- /usr/local/libexec/ai-server --'
find /usr/local/libexec/ai-server -maxdepth 2 -type f -printf '%M %u:%g %s %p\n' 2>/dev/null | sort || true
printf '%s\n' '-- relevant /usr/local/bin --'
find /usr/local/bin -maxdepth 1 -type f   \( -name 'hermes*' -o -name '*video*' -o -name '*foto*' -o -name 'ollama' \)   -printf '%M %u:%g %s %p\n' 2>/dev/null | sort || true

section "DEPLOYED VS WORKING TREE HASHES"
for rel in   pyproject.toml   src/ai_bridge/settings.py   src/ai_bridge/gateway/app.py   src/ai_bridge/gateway/scheduler.py   src/ai_bridge/gateway/resource_leases.py
do
  printf '\n-- %s --\n' "$rel"
  for root in "$HOME/AI-server" /opt/ai-bridge /opt/ai-gateway; do
    if [[ -f "$root/$rel" ]]; then
      printf '%s  ' "$root"
      sha256sum "$root/$rel" | awk '{print $1}'
    fi
  done
done

section "ENV FILE METADATA ONLY"
for f in   "$HOME/AI-server/.env"   /opt/ai-bridge/.env   /etc/ai-bridge/ai-bridge.env   /etc/ai-gateway/ai-gateway.env   /srv/ai-data/hermes/.env
do
  [[ -f "$f" ]] && stat -c '%A %U:%G %a %s %y %n' "$f" 2>/dev/null || true
done

section "SUPPLEMENT END"
printf 'READ_ONLY=true\n'
printf 'FINISHED_AT='; date --iso-8601=seconds 2>/dev/null || date
