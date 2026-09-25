#!/usr/bin/env python3
"""Stage M schema operations. Invoked deliberately from the immutable release."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from ai_bridge.storage.database import Database

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("stage_l_ops", ROOT / "deploy/stage-l/production_ops.py")
l = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l)
BASE_REVISION = "0004_ers_core_persistence"
TARGET_REVISION = "0005_crt_projection"
TABLES = {"crt_projects", "crt_sessions", "crt_session_artifacts", "crt_ers_links", "crt_ai_findings"}


def operation(action):
    url = l.database_url()
    os.environ["AI_BRIDGE_DATABASE_URL"] = url
    config = Config(str(ROOT / "alembic.ini"))
    if action == "upgrade":
        command.upgrade(config, TARGET_REVISION)
    elif action == "downgrade":
        command.downgrade(config, BASE_REVISION)
    db = Database(url)
    try:
        expected = BASE_REVISION if action in ("downgrade", "verify-inactive") else TARGET_REVISION
        with db.session() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            l.require(revision == expected, "schema mismatch")
            tables = set(inspect(db.engine).get_table_names())
            l.require((TABLES <= tables) if expected == TARGET_REVISION else not (TABLES & tables), "CRT table mismatch")
            l.require("ers_cases" in tables and "ers_case_events" in tables, "ERS baseline missing")
            cases = [dict(row) for row in session.execute(text("SELECT id, status, work_state, row_version FROM ers_cases ORDER BY id")).mappings()]
        return {"status": "PASS", "revision": revision, "cases": cases}
    finally:
        db.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("upgrade", "downgrade", "verify-active", "verify-inactive"))
    print(json.dumps(operation(parser.parse_args().action), default=str, sort_keys=True))
