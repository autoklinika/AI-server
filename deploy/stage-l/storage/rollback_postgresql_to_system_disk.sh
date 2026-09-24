#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE="/var/lib/postgresql/18/main"
TARGET="/srv/ai-data/platform/postgresql/18/main"
DROPIN="/etc/postgresql/18/main/conf.d/99-ai-platform-data-directory.conf"
APP_SERVICE="ai-bridge.service"

fail() {
  printf 'POSTGRES_ROLLBACK_FAIL=%s\n' "$1" >&2
  exit 64
}

[[ "$(id -u)" -eq 0 ]] || fail "root_required"
[[ $# -eq 1 ]] || fail "usage_retired_source_path"
RETIRED="$1"
[[ "$RETIRED" == /var/lib/postgresql/18/main.pre-ai-data-* ]] || fail "unexpected_retired_path"
[[ -f "$RETIRED/PG_VERSION" ]] || fail "retired_cluster_missing"
[[ "$(cat "$RETIRED/PG_VERSION")" == "18" ]] || fail "retired_version_mismatch"

CURRENT="$(pg_lsclusters -h | awk '$1=="18" && $2=="main" {print $6}')"
[[ "$CURRENT" == "$TARGET" ]] || fail "target_not_current"
[[ -f "$SOURCE/README_AI_PLATFORM_DATA_MOVED.txt" ]] || fail "system_stub_not_verified"
[[ ! -f "$SOURCE/PG_VERSION" ]] || fail "system_source_not_stub"

systemctl stop "$APP_SERVICE"
pg_ctlcluster 18 main stop

STUB="/var/lib/postgresql/18/main.data-disk-stub-$(date -u +%Y%m%dT%H%M%SZ)"
mv "$SOURCE" "$STUB"
mv "$RETIRED" "$SOURCE"
rm -f "$DROPIN"

pg_ctlcluster 18 main start
for _ in $(seq 1 30); do
  pg_isready -q -p 5432 && break
  sleep 1
done
pg_isready -q -p 5432 || fail "postgres_not_ready"

ACTIVE="$(runuser -u postgres -- psql -Atqc 'show data_directory')"
[[ "$ACTIVE" == "$SOURCE" ]] || fail "active_directory_mismatch"
runuser -u postgres -- psql -d ai_bridge -Atqc 'select 1' | grep -qx '1'   || fail "ai_bridge_database_unavailable"

systemctl start "$APP_SERVICE"
systemctl is-active --quiet "$APP_SERVICE" || fail "ai_bridge_not_active"

printf 'POSTGRES_ROLLBACK=PASS\n'
printf 'ACTIVE_DATA_DIRECTORY=%s\n' "$SOURCE"
printf 'DATA_DISK_COPY_PRESERVED=%s\n' "$TARGET"
printf 'STUB_ARCHIVE=%s\n' "$STUB"
