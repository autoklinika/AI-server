from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "deploy/stage-j/data_prepare.py"
SPEC = importlib.util.spec_from_file_location("stage_j_data_prepare", MODULE_PATH)
data_prepare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(data_prepare)

def test_parse_json_stream_accepts_multiple_documents() -> None:
    values = data_prepare.parse_json_stream("{\"job\": 1}\n{\n  \"summary\": {\"selected\": 0}\n}\n")
    assert values == [{"job": 1}, {"summary": {"selected": 0}}]

def test_postgres_env_converts_sqlalchemy_url_without_leaking_driver() -> None:
    env = data_prepare.postgres_env("postgresql+psycopg://ai_bridge:test%40pass@127.0.0.1:5432/ai_bridge")
    assert env["PGHOST"] == "127.0.0.1"
    assert env["PGPORT"] == "5432"
    assert env["PGUSER"] == "ai_bridge"
    assert env["PGPASSWORD"] == "test@pass"
    assert env["PGDATABASE"] == "ai_bridge"

def test_verify_objects_validates_content_addressed_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    objects = tmp_path / "objects"
    backups = tmp_path / "backups"
    content = b"canonical-evidence"
    digest = sha256(content).hexdigest()
    target = objects / "sha256" / digest[:2] / digest
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    monkeypatch.setattr(data_prepare, "OBJECT_ROOT", objects)
    monkeypatch.setattr(data_prepare, "BACKUP_ROOT", backups)
    result = data_prepare.verify_objects("a" * 40)
    assert result["objects"] == 1
    assert result["bytes"] == len(content)
    assert digest in Path(result["manifest"]).read_text()

def test_verify_objects_rejects_checksum_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    objects = tmp_path / "objects"
    backups = tmp_path / "backups"
    fake = "0" * 64
    target = objects / "sha256" / fake[:2] / fake
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong")
    monkeypatch.setattr(data_prepare, "OBJECT_ROOT", objects)
    monkeypatch.setattr(data_prepare, "BACKUP_ROOT", backups)
    with pytest.raises(RuntimeError, match="checksum"):
        data_prepare.verify_objects("b" * 40)
