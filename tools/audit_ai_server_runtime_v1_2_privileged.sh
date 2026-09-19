#!/usr/bin/env bash
# AI Server runtime audit v1.2 - privileged read-only checks
# READ-ONLY: firewall inspection + exact PostgreSQL telemetry counts/timestamps.
set -euo pipefail
export LC_ALL=C

section(){ printf '\n\n===== %s =====\n' "$1"; }

printf 'AI_SERVER_RUNTIME_AUDIT_VERSION=1.2\n'
printf 'READ_ONLY=true\n'
printf 'GENERATED_AT='; date --iso-8601=seconds 2>/dev/null || date

section "FIREWALL"
if command -v ufw >/dev/null 2>&1; then
  echo '$ sudo ufw status verbose'
  sudo ufw status verbose 2>&1 || true
fi

if command -v nft >/dev/null 2>&1; then
  echo
  echo '$ sudo nft list ruleset'
  sudo nft list ruleset 2>&1 || true
fi

section "AI BRIDGE TELEMETRY EXACT COUNTS"
if [[ -r /etc/ai-bridge/ai-bridge.env && -x /opt/ai-bridge/.venv/bin/python ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/ai-bridge/ai-bridge.env >/dev/null 2>&1
  set +a

  /opt/ai-bridge/.venv/bin/python - <<'PY'
import os
from sqlalchemy import create_engine, text

url = os.environ.get("AI_BRIDGE_DATABASE_URL")
if not url:
    print("database_url: unavailable")
    raise SystemExit(1)

engine = create_engine(url)
with engine.connect() as c:
    tables = c.execute(text("""
      select table_name
      from information_schema.tables
      where table_schema='public' and table_type='BASE TABLE'
      order by table_name
    """)).scalars().all()

    print("tables:")
    for table in tables:
        print(f"  {table}")

    print("\nexact_counts:")
    for table in tables:
        safe = '"' + table.replace('"', '""') + '"'
        count = c.execute(text(f'SELECT COUNT(*) FROM public.{safe}')).scalar()
        print(f"  {table}={count}")

    print("\ncolumns:")
    for table in tables:
        cols = c.execute(text("""
          select column_name, data_type
          from information_schema.columns
          where table_schema='public' and table_name=:table
          order by ordinal_position
        """), {"table": table}).all()
        print(f"  [{table}]")
        for name, dtype in cols:
            print(f"    {name}: {dtype}")

    # Try common timestamp columns without assuming schema.
    candidates = ("timestamp", "created_at", "received_at", "window_start", "window_end", "sample_time")
    print("\ntimestamp_ranges:")
    for table in tables:
        cols = {row[0] for row in c.execute(text("""
          select column_name
          from information_schema.columns
          where table_schema='public' and table_name=:table
        """), {"table": table}).all()}
        safe_table = '"' + table.replace('"', '""') + '"'
        for col in candidates:
            if col in cols:
                safe_col = '"' + col.replace('"', '""') + '"'
                row = c.execute(text(
                    f'SELECT MIN({safe_col}), MAX({safe_col}) FROM public.{safe_table}'
                )).one()
                print(f"  {table}.{col}: min={row[0]} max={row[1]}")
PY
  unset AI_BRIDGE_DATABASE_URL
else
  echo "database metadata skipped: env/python unavailable"
fi

section "END"
printf 'READ_ONLY=true\n'
printf 'FINISHED_AT='; date --iso-8601=seconds 2>/dev/null || date
