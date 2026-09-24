#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED="/srv/ai-data/platform/postgresql/18/main"

fail() {
  printf 'POSTGRES_DATA_DISK_FAIL=%s\n' "$1" >&2
  exit 64
}

[[ "$(id -u)" -eq 0 ]] || fail "root_required"

SYSTEM_DEVICE="$(findmnt -n -o SOURCE -T /)"
DATA_DEVICE="$(findmnt -n -o SOURCE -T /srv/ai-data)"
TARGET_DEVICE="$(findmnt -n -o SOURCE -T "$EXPECTED")"
CLUSTER_DIR="$(pg_lsclusters -h | awk '$1=="18" && $2=="main" {print $6}')"
ACTIVE_DIR="$(runuser -u postgres -- psql -Atqc 'show data_directory')"

printf 'SYSTEM_DEVICE=%s\n' "$SYSTEM_DEVICE"
printf 'DATA_DEVICE=%s\n' "$DATA_DEVICE"
printf 'TARGET_DEVICE=%s\n' "$TARGET_DEVICE"
printf 'CLUSTER_DATA_DIRECTORY=%s\n' "$CLUSTER_DIR"
printf 'ACTIVE_DATA_DIRECTORY=%s\n' "$ACTIVE_DIR"

[[ -n "$SYSTEM_DEVICE" && -n "$DATA_DEVICE" && -n "$TARGET_DEVICE" ]] || fail "mount_detection"
[[ "$SYSTEM_DEVICE" != "$DATA_DEVICE" ]] || fail "ai_data_not_separate_device"
[[ "$TARGET_DEVICE" == "$DATA_DEVICE" ]] || fail "postgres_target_not_on_ai_data"
[[ "$CLUSTER_DIR" == "$EXPECTED" ]] || fail "cluster_directory_mismatch"
[[ "$ACTIVE_DIR" == "$EXPECTED" ]] || fail "active_directory_mismatch"

[[ -f "$EXPECTED/PG_VERSION" ]] || fail "pg_version_missing"
[[ "$(cat "$EXPECTED/PG_VERSION")" == "18" ]] || fail "pg_version_mismatch"
pg_isready -q -p 5432 || fail "postgres_not_ready"

runuser -u postgres -- psql -d ai_bridge -Atqc 'select 1' | grep -qx '1'   || fail "ai_bridge_database_unavailable"

systemctl is-active --quiet postgresql@18-main.service || fail "postgres_service_not_active"
systemctl is-active --quiet ai-bridge.service || fail "ai_bridge_service_not_active"

printf 'POSTGRES_DATA_DISK=PASS\n'
