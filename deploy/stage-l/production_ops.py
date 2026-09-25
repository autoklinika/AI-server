#!/usr/bin/env python3
"""Fail-closed Stage L database/import operations.

This helper is executed as the non-root AI Platform owner from the immutable
candidate release. It reads the production database URL from the existing
root-owned/group-readable AI Bridge env file and never prints it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from ai_bridge.domains.ers.legacy_seed import LegacySeedImporter
from ai_bridge.domains.ers.storage.models import (
    ErsArtifactModel,
    ErsArtifactVersionModel,
    ErsCaseEventModel,
    ErsCaseModel,
)
from ai_bridge.storage.database import Database
from ai_bridge.storage.object_store import FileObjectStore


ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path("/etc/ai-bridge/ai-bridge.env")
ERS_ROOT = Path("/srv/ai-data/knowledge/source-cache/EcuRepairService")
OBJECT_ROOT = Path("/srv/ai-data/knowledge/canonical/objects")
TARGET_REVISION = "0004_ers_core_persistence"
BASE_REVISION = "0003_knowledge_canonical"
EXPECTED = {
    "CASE-0001-GAYK-HRE3000USP-HATZ-3H50TICD-SPN107-FMI3": {
        "status": "closed",
        "work_state": "none",
        "artifacts": 17,
    },
    "CASE-0002-SCANIA-EMS-S6-DC1210-ECU-CLONE": {
        "status": "open",
        "work_state": "verifying",
        "artifacts": 16,
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def database_url() -> str:
    require(ENV_FILE.is_file(), "AI Bridge env file missing")
    values: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    url = values.get("AI_BRIDGE_DATABASE_URL", "")
    require(bool(url), "AI_BRIDGE_DATABASE_URL missing")
    return url


def source_revision() -> str:
    require(ERS_ROOT.is_dir(), "ERS source root missing")
    status = subprocess.run(
        ["git", "-C", str(ERS_ROOT), "status", "--porcelain", "--untracked-files=no"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    require(not status, "ERS source root has tracked modifications")
    revision = subprocess.run(
        ["git", "-C", str(ERS_ROOT), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    require(len(revision) == 40, "ERS source revision unavailable")
    return revision


def alembic(action: str) -> dict[str, object]:
    url = database_url()
    os.environ["AI_BRIDGE_DATABASE_URL"] = url
    config = Config(str(ROOT / "alembic.ini"))
    if action == "upgrade":
        command.upgrade(config, TARGET_REVISION)
        expected = TARGET_REVISION
    elif action == "downgrade":
        command.downgrade(config, BASE_REVISION)
        expected = BASE_REVISION
    else:
        raise ValueError(action)
    db = Database(url)
    try:
        with db.session() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        require(revision == expected, "unexpected Alembic revision")
    finally:
        db.dispose()
    return {"status": "PASS", "action": action, "revision": expected}


def plan_importer() -> tuple[LegacySeedImporter, list, str]:
    revision = source_revision()
    planner = LegacySeedImporter()
    plans = []
    for legacy in EXPECTED:
        seed = ERS_ROOT / "cases" / legacy / "case.seed.json"
        plans.append(planner.plan(seed, source_revision=revision))
    return planner, plans, revision


def apply_import() -> dict[str, object]:
    url = database_url()
    _planner, plans, revision = plan_importer()
    db = Database(url)
    store = FileObjectStore(OBJECT_ROOT)
    importer = LegacySeedImporter(database=db, object_store=store)
    try:
        outcomes = [importer.apply(plan) for plan in plans]
    finally:
        db.dispose()
    require({row.legacy_case_code for row in outcomes} == set(EXPECTED), "legacy case set mismatch")
    require(all(row.state in {"created", "reused"} for row in outcomes), "legacy import state invalid")
    return {
        "status": "PASS",
        "source_revision": revision,
        "cases": [
            {
                "case_id": str(row.case_id),
                "case_code": row.case_code,
                "legacy_case_code": row.legacy_case_code,
                "state": row.state,
                "artifacts": row.artifacts,
                "fingerprint": row.fingerprint,
            }
            for row in outcomes
        ],
    }


def verify_active() -> dict[str, object]:
    url = database_url()
    db = Database(url)
    try:
        with db.session() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            require(revision == TARGET_REVISION, "ERS schema revision is not active")
            rows = session.scalars(
                select(ErsCaseModel)
                .where(ErsCaseModel.legacy_case_code.in_(tuple(EXPECTED)))
                .order_by(ErsCaseModel.legacy_case_code)
            ).all()
            require(len(rows) == 2, "expected two imported legacy cases")
            details = []
            for case in rows:
                expected = EXPECTED[str(case.legacy_case_code)]
                require(case.status == expected["status"], "legacy case status mismatch")
                require(case.work_state == expected["work_state"], "legacy case work_state mismatch")
                events = session.scalars(
                    select(ErsCaseEventModel)
                    .where(ErsCaseEventModel.case_id == case.id)
                    .order_by(ErsCaseEventModel.event_seq)
                ).all()
                require(len(events) == case.row_version, "case event count mismatch")
                require([row.event_seq for row in events] == list(range(1, case.row_version + 1)),
                        "case event sequence mismatch")
                artifact_count = session.scalar(
                    select(func.count())
                    .select_from(ErsArtifactModel)
                    .where(ErsArtifactModel.case_id == case.id)
                )
                require(artifact_count == expected["artifacts"], "artifact count mismatch")
                versions = session.scalars(
                    select(ErsArtifactVersionModel)
                    .join(ErsArtifactModel, ErsArtifactModel.id == ErsArtifactVersionModel.artifact_id)
                    .where(
                        ErsArtifactModel.case_id == case.id,
                        ErsArtifactVersionModel.availability == "available",
                    )
                ).all()
                for version in versions:
                    require(version.object_sha256 is not None, "available object hash missing")
                    stored = FileObjectStore(OBJECT_ROOT).verify(version.object_sha256)
                    require(stored.byte_size == version.byte_size, "object size mismatch")
                details.append({
                    "case_id": str(case.id),
                    "legacy_case_code": case.legacy_case_code,
                    "case_code": case.case_code,
                    "status": case.status,
                    "work_state": case.work_state,
                    "row_version": case.row_version,
                    "events": len(events),
                    "artifacts": artifact_count,
                })
            total_artifacts = session.scalar(select(func.count()).select_from(ErsArtifactModel))
            total_versions = session.scalar(select(func.count()).select_from(ErsArtifactVersionModel))
            require(total_artifacts == 33 and total_versions == 33, "ERS artifact totals mismatch")
        return {
            "status": "PASS",
            "revision": revision,
            "cases": details,
            "total_artifacts": total_artifacts,
            "total_versions": total_versions,
        }
    finally:
        db.dispose()


def verify_inactive() -> dict[str, object]:
    url = database_url()
    db = Database(url)
    try:
        with db.session() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            require(revision == BASE_REVISION, "base schema revision mismatch")
            count = session.execute(text(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname='public' AND tablename LIKE 'ers_%'"
            )).scalar_one()
            require(count == 0, "ERS tables remain after downgrade")
        return {"status": "PASS", "revision": revision, "ers_tables": 0}
    finally:
        db.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("upgrade", "downgrade", "import", "verify-active", "verify-inactive"))
    args = parser.parse_args()
    if args.action == "upgrade":
        result = alembic("upgrade")
    elif args.action == "downgrade":
        result = alembic("downgrade")
    elif args.action == "import":
        result = apply_import()
    elif args.action == "verify-active":
        result = verify_active()
    else:
        result = verify_inactive()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
