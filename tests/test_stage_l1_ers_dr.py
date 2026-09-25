from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGE_K = ROOT / "deploy" / "stage-k"
sys.path.insert(0, str(STAGE_K))

import backup  # noqa: E402
import common  # noqa: E402
import ers_dr  # noqa: E402
import k5_retention  # noqa: E402
import k5_run  # noqa: E402
import restore_validate  # noqa: E402
import verify_backup  # noqa: E402


class FakeCursor:
    def __init__(
        self,
        *,
        active: bool,
        tables: list[str] | None = None,
        counts: dict[str, int] | None = None,
        availability: list[tuple[str, int]] | None = None,
        objects: list[tuple[str, int, int]] | None = None,
        boundaries: list[tuple[str, int, int, int, int]] | None = None,
    ) -> None:
        self.active = active
        self.tables = tables or []
        self.counts = counts or {}
        self.availability = availability or []
        self.objects = objects or []
        self.boundaries = boundaries or []
        self.rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql: str, _params=None):
        normalized = " ".join(sql.split())
        if "to_regclass('public.ers_cases')" in normalized:
            self.rows = [("ers_cases" if self.active else None,)]
        elif "SELECT tablename FROM pg_tables" in normalized:
            self.rows = [(name,) for name in self.tables]
        elif normalized.startswith('SELECT count(*) FROM "ers_'):
            table = normalized.split('"')[1]
            self.rows = [(self.counts[table],)]
        elif "SELECT availability, count(*)" in normalized:
            self.rows = list(self.availability)
        elif (
            "SELECT object_sha256, byte_size, count(*)" in normalized
            and "ers_artifact_versions" in normalized
        ):
            self.rows = list(self.objects)
        elif "SELECT c.id::text, c.row_version" in normalized:
            self.rows = list(self.boundaries)
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def active_snapshot(data: bytes = b"ers-object") -> tuple[dict, bytes]:
    digest = hashlib.sha256(data).hexdigest()
    tables = sorted(ers_dr.CORE_ERS_TABLES)
    counts = {name: 0 for name in tables}
    counts.update({
        "ers_cases": 1,
        "ers_case_events": 3,
        "ers_artifacts": 2,
        "ers_artifact_versions": 2,
    })
    cursor = FakeCursor(
        active=True,
        tables=tables,
        counts=counts,
        availability=[("available", 2)],
        objects=[(digest, len(data), 2)],
        boundaries=[("00000000-0000-0000-0000-000000000001", 3, 3, 3, 1)],
    )
    return ers_dr.fetch_snapshot_metadata(FakeConnection(cursor)), data


def test_ers_snapshot_is_optional_before_schema_0004():
    snapshot = ers_dr.fetch_snapshot_metadata(
        FakeConnection(FakeCursor(active=False))
    )
    assert snapshot == {
        "active": False,
        "table_counts": {},
        "availability_counts": {},
        "available_versions": 0,
        "objects": [],
        "case_boundaries": [],
    }


def test_active_ers_snapshot_and_object_pool_are_deterministic(tmp_path):
    snapshot, data = active_snapshot()
    digest = snapshot["objects"][0]["sha256"]
    source = tmp_path / "source" / "sha256" / digest[:2] / digest
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    source.chmod(0o444)

    first = ers_dr.copy_object_set(
        snapshot, tmp_path / "nas" / "ERS" / "object-store",
        source_root=tmp_path / "source",
    )
    second = ers_dr.copy_object_set(
        snapshot, tmp_path / "nas" / "ERS" / "object-store",
        source_root=tmp_path / "source",
    )

    assert first["objects"] == 1
    assert first["referenced_versions"] == 2
    assert first["copied_objects"] == 1
    assert second["copied_objects"] == 0
    assert second["reused_objects"] == 1
    assert first["files"][0]["path"] == f"sha256/{digest[:2]}/{digest}"


def test_active_ers_snapshot_rejects_incomplete_schema():
    tables = sorted(ers_dr.CORE_ERS_TABLES - {"ers_evidence"})
    cursor = FakeCursor(active=True, tables=tables)
    with pytest.raises(common.StageKError, match="ERS schema incomplete"):
        ers_dr.fetch_snapshot_metadata(FakeConnection(cursor))


def test_verify_ers_case_store_manifest_checks_shared_dump_and_objects(
    tmp_path, monkeypatch
):
    root = tmp_path / "AI_Platform"
    backup_id = "20260925T100000Z"
    manifest_dir = (
        root / "ERS" / "case-store" / "manifests" / "manual" / backup_id
    )
    manifest_dir.mkdir(parents=True)
    dump = (
        root / "_Shared" / "PostgreSQL" / "ai_bridge" / "manual"
        / backup_id / "ai_bridge.dump"
    )
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"fake-custom-dump")

    data = b"verified-ers-object"
    digest = hashlib.sha256(data).hexdigest()
    object_path = root / "ERS" / "object-store" / "sha256" / digest[:2] / digest
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(data)

    table_counts = {name: 0 for name in sorted(ers_dr.CORE_ERS_TABLES)}
    table_counts["ers_cases"] = 1
    table_counts["ers_case_events"] = 1
    table_counts["ers_artifact_versions"] = 1
    boundary = {
        "case_id": "00000000-0000-0000-0000-000000000001",
        "row_version": 1,
        "event_count": 1,
        "max_event_seq": 1,
        "min_event_seq": 1,
    }
    manifest = {
        "manifest_schema_version": 1,
        "status": "COMPLETE",
        "domain": "ERSCaseStore",
        "backup_id": backup_id,
        "secrets_included": False,
        "postgres": {
            "dump": {
                "path": dump.relative_to(root).as_posix(),
                "bytes": dump.stat().st_size,
                "sha256": common.file_sha256(dump),
                "format": "custom",
            },
            "table_counts": dict(table_counts),
            "domain_table_counts": dict(table_counts),
        },
        "ers": {
            "available_versions": 1,
            "availability_counts": {"available": 1},
            "case_boundaries": [boundary],
            "object_set": {
                "objects": 1,
                "bytes": len(data),
                "referenced_versions": 1,
                "pool_root": "ERS/object-store",
                "files": [{
                    "sha256": digest,
                    "bytes": len(data),
                    "path": f"sha256/{digest[:2]}/{digest}",
                    "referenced_versions": 1,
                }],
            },
        },
    }
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    (manifest_dir / "manifest.sha256").write_text(
        common.file_sha256(manifest_path) + "  manifest.json\n"
    )
    (manifest_dir / "COMPLETE").write_text(backup_id + "\n")

    monkeypatch.setattr(verify_backup, "run", lambda *_a, **_kw: "")
    result = verify_backup.verify(manifest_dir)
    assert result["status"] == "PASS"
    assert result["ers_case_count"] == 1
    assert result["ers_object_set"]["objects"] == 1
    assert result["ers_object_set"]["referenced_versions"] == 1


def test_full_restore_requires_ers_manifest_when_dump_contains_ers(
    tmp_path, monkeypatch
):
    backup = tmp_path / "AI_Platform" / "Knowledge" / "manifests" / "manual" / "id"
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_text(json.dumps({
        "backup_id": "id",
        "postgres": {
            "table_counts": {"knowledge_documents": 1, "ers_cases": 1},
        },
    }))
    monkeypatch.setattr(
        restore_validate, "verify_backup",
        lambda _path: {"status": "PASS"},
    )
    with pytest.raises(
        common.StageKError,
        match="ERS Case Store manifest is required",
    ):
        restore_validate.validate(backup)


def test_k5_weekly_passes_matching_ers_manifest_to_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(k5_run, "STATUS_ROOT", tmp_path / "status")
    monkeypatch.setattr(k5_run, "LOCK_PATH", tmp_path / "status" / "run.lock")
    monkeypatch.setattr(k5_run, "TARGET_ROOT", tmp_path / "AI_Platform")
    k5_run.TARGET_ROOT.mkdir()
    monkeypatch.setattr(k5_run, "git_head", lambda: "a" * 40)
    monkeypatch.setattr(k5_run, "notify", lambda *_a, **_kw: None)

    calls: list[tuple[str, list[str]]] = []

    def fake_run_json(label, args, timeout):
        calls.append((label, list(args)))
        if label == "knowledge_backup":
            return {
                "status": "PASS",
                "knowledge_set": "/backup/knowledge/id",
                "wvc_set": "/backup/wvc/id",
                "ers_set": "/backup/ers/id",
            }
        if label == "domain_backup":
            return {
                "status": "PASS",
                "backup_id": "id",
                "ers_manifest": "/backup/k3/ers/id",
                "hermes_manifest": "/backup/k3/hermes/id",
                "platform_manifest": "/backup/k3/platform/id",
            }
        return {"status": "PASS"}

    monkeypatch.setattr(k5_run, "run_json", fake_run_json)
    result = k5_run.run("weekly")
    restore_args = dict(calls)["restore_knowledge"]
    assert "--ers" in restore_args
    assert restore_args[restore_args.index("--ers") + 1] == "/backup/ers/id"
    assert result["ers_case_store_verify"] == {"status": "PASS"}


def write_complete_manifest(path: Path, backup_id: str, table_counts: dict) -> None:
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({
        "status": "COMPLETE",
        "backup_id": backup_id,
        "postgres": {"table_counts": table_counts},
    }))
    (path / "COMPLETE").write_text(backup_id + "\n")


def test_retention_requires_ers_pair_for_ers_active_backup(tmp_path):
    root = tmp_path / "AI_Platform"
    old, new = "20260101T000000Z", "20260102T000000Z"
    for backup_id in (old, new):
        write_complete_manifest(
            root / "Knowledge" / "manifests" / "daily" / backup_id,
            backup_id,
            {"knowledge_documents": 1, "ers_cases": 1},
        )
        write_complete_manifest(
            root / "WVC" / "manifests" / "daily" / backup_id,
            backup_id,
            {"knowledge_documents": 1, "ers_cases": 1},
        )
        dump = (
            root / "_Shared" / "PostgreSQL" / "ai_bridge" / "daily"
            / backup_id / "ai_bridge.dump"
        )
        dump.parent.mkdir(parents=True)
        dump.write_bytes(b"dump")

    with pytest.raises(common.StageKError, match="paired ERS Case Store"):
        k5_retention.prune_k2(root, "daily", keep=1)

    write_complete_manifest(
        root / "ERS" / "case-store" / "manifests" / "daily" / old,
        old,
        {"ers_cases": 1},
    )
    removed = k5_retention.prune_k2(root, "daily", keep=1)
    assert removed == [old]
    assert not (
        root / "ERS" / "case-store" / "manifests" / "daily" / old
    ).exists()


def test_stage_k_release_identity_accepts_stage_l(tmp_path, monkeypatch):
    release = tmp_path / "release"
    release.mkdir()
    (release / "RELEASE").write_text(
        "stage=L\n"
        "release_id=stage-l-test\n"
        f"source_git_sha={'b' * 40}\n"
    )
    monkeypatch.setattr(backup, "active_release", lambda: release)
    identity = backup.release_identity()
    assert identity["stage"] == "L"
    assert identity["source_git_sha"] == "b" * 40
