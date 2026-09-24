#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED="/srv/ai-data/platform/postgresql/18/main"
SYSTEM_MOUNT="$(findmnt -n -o SOURCE -T /)"
DATA_MOUNT="$(findmnt -n -o SOURCE -T /srv/ai-data)"
CURRENT="$(pg_lsclusters -h | awk '$1=="18" && $2=="main" {print $6}')"

printf 'SYSTEM_DEVICE=%s\n' "$SYSTEM_MOUNT"
printf 'DATA_DEVICE=%s\n' "$DATA_MOUNT"
printf 'POSTGRES_DATA_DIRECTORY=%s\n' "$CURRENT"

[[ -n "$SYSTEM_MOUNT" && -n "$DATA_MOUNT" ]]
[[ "$SYSTEM_MOUNT" != "$DATA_MOUNT" ]]
[[ "$CURRENT" == "$EXPECTED" ]]
[[ -f "$EXPECTED/PG_VERSION" ]]
[[ "$(cat "$EXPECTED/PG_VERSION")" == "18" ]]
pg_isready -q -p 5432

printf 'POSTGRES_DATA_DISK=PASS\n'
