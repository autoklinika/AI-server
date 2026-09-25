"""CRT metadata DR extension to the shared PostgreSQL snapshot.

CRT owns capture bytes externally; no CRT object namespace is introduced here.
"""
import hashlib
import json
from common import require

REVISION = "0005_crt_projection"
TABLES = ("crt_projects", "crt_sessions", "crt_session_artifacts", "crt_ers_links", "crt_ai_findings")


def snapshot(conn):
    tables = {}
    with conn.cursor() as cur:
        cur.execute("SET LOCAL TIME ZONE 'UTC'")
        for table in TABLES:
            digest = hashlib.sha256()
            count = 0
            cur.execute(f'SELECT row_to_json(t) FROM (SELECT * FROM "{table}" ORDER BY id) t')
            while True:
                rows = cur.fetchmany(256)
                if not rows:
                    break
                for (row,) in rows:
                    digest.update(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
                    digest.update(b"\n")
                    count += 1
            tables[table] = {"count": count, "sha256": digest.hexdigest()}
    return {"contract_version": 1, "objects": "external-crt-owned", "tables": tables}


def validate(postgres):
    crt = postgres.get("crt")
    if postgres.get("schema_version") != REVISION:
        require(crt is None and not any(name.startswith("crt_") for name in postgres.get("table_counts", {})), "unexpected CRT backup contract")
        return
    require(isinstance(crt, dict), "missing CRT backup metadata")
    require(crt.get("contract_version") == 1, "unsupported CRT backup contract")
    require(crt.get("objects") == "external-crt-owned", "unsupported CRT object namespace")
    require(set(crt["tables"]) == set(TABLES), "incomplete CRT table set")
    import re
    for table, entry in crt["tables"].items():
        require(type(entry["count"]) is int and entry["count"] >= 0, "invalid CRT count")
        require(entry["count"] == postgres["table_counts"][table], "CRT count mismatch")
        require(re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is not None, "invalid CRT digest")


def verify_restored(conn, postgres):
    validate(postgres)
    if postgres.get("crt") is not None:
        require(snapshot(conn) == postgres["crt"], "restored CRT metadata digest mismatch")
