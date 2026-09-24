#!/usr/bin/env bash
set -Eeuo pipefail

PG_VERSION="18"
PG_CLUSTER="main"
SOURCE="/var/lib/postgresql/18/main"
TARGET="/srv/ai-data/platform/postgresql/18/main"
CONF_DIR="/etc/postgresql/18/main/conf.d"
DROPIN="$CONF_DIR/99-ai-platform-data-directory.conf"
BACKUP_ROOT="/mnt/AI_Platform"
APP_SERVICE="ai-bridge.service"

fail() {
  printf 'POSTGRES_RELOCATE_FAIL=%s\n' "$1" >&2
  exit 64
}

[[ "$(id -u)" -eq 0 ]] || fail "root_required"
[[ $# -eq 1 ]] || fail "usage_backup_id"
BACKUP_ID="$1"
[[ "$BACKUP_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || fail "invalid_backup_id"

KNOWLEDGE_SET="$BACKUP_ROOT/Knowledge/manifests/manual/$BACKUP_ID"
PG_DUMP="$BACKUP_ROOT/_Shared/PostgreSQL/ai_bridge/manual/$BACKUP_ID/ai_bridge.dump"

[[ -f "$KNOWLEDGE_SET/COMPLETE" ]] || fail "backup_incomplete"
[[ -s "$PG_DUMP" ]] || fail "postgres_backup_missing"
pg_restore -l "$PG_DUMP" >/dev/null || fail "postgres_backup_invalid"

ROOT_SOURCE="$(findmnt -n -o SOURCE -T /)"
DATA_SOURCE="$(findmnt -n -o SOURCE -T /srv/ai-data)"
[[ -n "$ROOT_SOURCE" && -n "$DATA_SOURCE" ]] || fail "mount_detection"
[[ "$ROOT_SOURCE" != "$DATA_SOURCE" ]] || fail "ai_data_not_separate_device"
mountpoint -q /srv/ai-data || fail "ai_data_not_mountpoint"

[[ -f "$SOURCE/PG_VERSION" ]] || fail "source_cluster_missing"
[[ "$(cat "$SOURCE/PG_VERSION")" == "$PG_VERSION" ]] || fail "pg_version_mismatch"
command -v rsync >/dev/null || fail "rsync_missing"
command -v pg_ctlcluster >/dev/null || fail "pg_ctlcluster_missing"
command -v pg_isready >/dev/null || fail "pg_isready_missing"

CURRENT_DIR="$(pg_lsclusters -h | awk -v v="$PG_VERSION" -v c="$PG_CLUSTER" '$1==v && $2==c {print $6}')"
if [[ "$CURRENT_DIR" == "$TARGET" ]]; then
  printf 'POSTGRES_RELOCATE=ALREADY_DONE\n'
  exit 0
fi
[[ "$CURRENT_DIR" == "$SOURCE" ]] || fail "unexpected_current_data_directory"

if [[ -e "$TARGET" ]]; then
  [[ -d "$TARGET" ]] || fail "target_not_directory"
  [[ -z "$(find "$TARGET" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "target_not_empty"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RETIRED="/var/lib/postgresql/18/main.pre-ai-data-$STAMP"
DROPIN_CREATED=0
PG_STOPPED=0
APP_STOPPED=0

rollback_on_error() {
  rc="${1:-$?}"
  trap - ERR
  printf 'POSTGRES_RELOCATE_ROLLBACK=BEGIN rc=%s\n' "$rc" >&2

  # Keep application writes stopped while PostgreSQL is rolled back.
  systemctl stop "$APP_SERVICE" || true
  APP_STOPPED=1

  # If the new cluster was started, stop it before removing its config.
  if [[ "$DROPIN_CREATED" -eq 1 ]]; then
    pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" stop || true
    PG_STOPPED=1
    rm -f "$DROPIN"
  fi

  # If the old directory was already retired, restore it before restart.
  if [[ -d "$RETIRED" ]]; then
    if [[ -e "$SOURCE" ]]; then
      mv "$SOURCE" "/var/lib/postgresql/18/main.failed-migration-$STAMP" || true
    fi
    mv "$RETIRED" "$SOURCE" || true
  fi

  if [[ "$PG_STOPPED" -eq 1 ]]; then
    pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" start || true
  fi
  if [[ "$APP_STOPPED" -eq 1 ]]; then
    systemctl start "$APP_SERVICE" || true
  fi
  printf 'POSTGRES_RELOCATE_ROLLBACK=END\n' >&2
  exit "$rc"
}

abort_migration() {
  printf 'POSTGRES_RELOCATE_FAIL=%s\n' "$1" >&2
  rollback_on_error 64
}

trap 'rollback_on_error $?' ERR

systemctl stop "$APP_SERVICE"
APP_STOPPED=1
pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" stop
PG_STOPPED=1

install -d -o postgres -g postgres -m 0750 /srv/ai-data/platform/postgresql/18
install -d -o postgres -g postgres -m 0700 "$TARGET"

rsync -aHAX --numeric-ids --delete "$SOURCE/" "$TARGET/"
if [[ -n "$(rsync -aHAXnc --numeric-ids --delete --itemize-changes "$SOURCE/" "$TARGET/")" ]]; then
  abort_migration "copy_verification_failed"
fi

install -d -o postgres -g postgres -m 0755 "$CONF_DIR"
tmp_dropin="$CONF_DIR/.99-ai-platform-data-directory.conf.$$.tmp"
printf "data_directory = '%s'\n" "$TARGET" > "$tmp_dropin"
chown postgres:postgres "$tmp_dropin"
chmod 0644 "$tmp_dropin"
mv "$tmp_dropin" "$DROPIN"
DROPIN_CREATED=1

pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" start
PG_STOPPED=0

for _ in $(seq 1 30); do
  if pg_isready -q -p 5432; then
    break
  fi
  sleep 1
done
pg_isready -q -p 5432 || abort_migration "postgres_not_ready"

ACTIVE_DIR="$(runuser -u postgres -- psql -Atqc 'show data_directory')"
[[ "$ACTIVE_DIR" == "$TARGET" ]] || abort_migration "active_data_directory_mismatch"
runuser -u postgres -- psql -d ai_bridge -Atqc 'select 1' | grep -qx '1' \
  || abort_migration "ai_bridge_database_unavailable"

systemctl start "$APP_SERVICE"
APP_STOPPED=0
systemctl is-active --quiet "$APP_SERVICE" || abort_migration "ai_bridge_not_active"

# Make accidental fallback to the stale system-disk cluster fail closed.
mv "$SOURCE" "$RETIRED"
install -d -o postgres -g postgres -m 0700 "$SOURCE"
cat > "$SOURCE/README_AI_PLATFORM_DATA_MOVED.txt" <<EOF
PostgreSQL production data moved to:
$TARGET

Migration:
$STAMP

Recovery backup:
$PG_DUMP

Do not copy new production data into this directory.
EOF
chown postgres:postgres "$SOURCE/README_AI_PLATFORM_DATA_MOVED.txt"
chmod 0400 "$SOURCE/README_AI_PLATFORM_DATA_MOVED.txt"

sync
trap - ERR

printf 'POSTGRES_RELOCATE=PASS\n'
printf 'BACKUP_ID=%s\n' "$BACKUP_ID"
printf 'SYSTEM_DEVICE=%s\n' "$ROOT_SOURCE"
printf 'DATA_DEVICE=%s\n' "$DATA_SOURCE"
printf 'ACTIVE_DATA_DIRECTORY=%s\n' "$TARGET"
printf 'RETIRED_SOURCE_COPY=%s\n' "$RETIRED"
printf 'DROPIN=%s\n' "$DROPIN"
printf 'ROLLBACK_NOTE=remove drop-in, restore retired directory as main, then start cluster\n'
