from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/stage-k"))
import crt_dr


def test_migration_roundtrip_preserves_stage_l(monkeypatch, tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "migration.db")
    monkeypatch.setenv("AI_BRIDGE_DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "0004_ers_core_persistence")
    engine = create_engine(url)
    before = set(inspect(engine).get_table_names())
    with engine.begin() as db:
        db.execute(text("UPDATE ers_case_counters SET next_value=19 WHERE counter_name='case'"))
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) - before == set(crt_dr.TABLES)
    command.downgrade(config, "0004_ers_core_persistence")
    assert set(inspect(engine).get_table_names()) == before
    with engine.connect() as db:
        assert db.scalar(text("SELECT next_value FROM ers_case_counters WHERE counter_name='case'")) == 19
    command.upgrade(config, "head")
    assert set(crt_dr.TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()


class Cursor:
    def __init__(self, rows): self.rows = rows
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql):
        if sql.startswith("SET LOCAL"): return
        self.pending = [(row,) for row in self.rows[sql.split('"')[1]]]
    def fetchmany(self, size):
        result, self.pending = self.pending[:size], self.pending[size:]
        return result


class Connection:
    def __init__(self, rows): self.rows = rows
    def cursor(self): return Cursor(self.rows)


def test_crt_dr_metadata_roundtrip_and_tamper_rejection():
    rows = {table: [{"id": table, "value": "provenance"}] for table in crt_dr.TABLES}
    conn = Connection(rows)
    snapshot = crt_dr.snapshot(conn)
    postgres = {"schema_version": crt_dr.REVISION, "crt": snapshot,
        "table_counts": {table: 1 for table in crt_dr.TABLES}}
    crt_dr.validate(postgres)
    crt_dr.verify_restored(conn, postgres)
    conn.rows["crt_sessions"][0]["value"] = "tampered"
    with pytest.raises(RuntimeError, match="digest mismatch"):
        crt_dr.verify_restored(conn, postgres)
    bad = deepcopy(postgres)
    del bad["crt"]["tables"]["crt_ai_findings"]
    with pytest.raises(RuntimeError): crt_dr.validate(bad)
    with pytest.raises(RuntimeError): crt_dr.validate({"schema_version": crt_dr.REVISION})
    crt_dr.validate({"schema_version": "0004_ers_core_persistence"})


def load_gate():
    spec = importlib.util.spec_from_file_location("stage_m_gate_test", ROOT / "deploy/stage-m/autopilot/gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def test_release_and_gate_contract():
    gate = load_gate()
    assert gate.BASE_SHA == "96f0ec239464f728aca2a7cf374670c9cd9be210"
    assert gate.BASE_REVISION == "0004_ers_core_persistence"
    assert gate.TARGET_REVISION == crt_dr.REVISION
    assert {"ers", "crt", "crt_ai_boundary", "knowledge", "wvc", "hermes_inference", "messaging_boundary"} <= set(gate.CHECKS)
    for step in ("00_preflight", "10_build_install", "20_cutover", "30_smoke", "40_rollback", "50_rollback_smoke", "60_reactivate", "70_reactivate_smoke", "90_finalize"):
        assert (ROOT / f"deploy/stage-m/autopilot/{step}.sh").is_file()
    assert "RELEASE_CRT_CONTRACT=1" in (ROOT / "deploy/stage-m/build_release.sh").read_text()
    spec = importlib.util.spec_from_file_location("stage_m_metadata", ROOT / "deploy/stage-m/validate_release_metadata.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.base.VERSIONS["crt_domain_contract_version"] == "1"
    assert module.base.VERSIONS["stage"] == "M"


def test_checkpoint_checksum_failure_never_executes_restore(monkeypatch, tmp_path):
    gate = load_gate()
    monkeypatch.setattr(gate, "STATE", tmp_path)
    (tmp_path / "sha").mkdir()
    (tmp_path / "sha/crt-checkpoint.json").write_text(json.dumps({"sql": "tampered", "sha256": "0" * 64}))
    calls = []
    monkeypatch.setattr(gate.e, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError): gate.restore_checkpoint({"source_sha": "sha"})
    assert calls == []


@pytest.mark.parametrize("activating", [True, False])
def test_schema_switch_order_with_all_production_effects_mocked(monkeypatch, tmp_path, activating):
    gate = load_gate()
    candidate = tmp_path / "candidate"
    current = tmp_path / "current"
    current.symlink_to(gate.BASE if activating else candidate)
    calls = []
    monkeypatch.setattr(gate.e, "CURRENT", current)
    monkeypatch.setattr(gate, "verify_release", lambda _: {})
    monkeypatch.setattr(gate.e, "clients", lambda: {})
    monkeypatch.setattr(gate.e, "quiesce", lambda *args, **kwargs: calls.append("quiesce"))
    monkeypatch.setattr(gate.e, "comfy_idle", lambda: None)
    monkeypatch.setattr(gate.e, "run", lambda args, **kwargs: "inactive" if "show" in args else calls.append(tuple(args)))
    monkeypatch.setattr(gate.e, "runtime", lambda *args: None)
    monkeypatch.setattr(gate.e, "resume_ingress", lambda *args: calls.append("resume"))
    monkeypatch.setattr(gate, "schema_version", lambda: gate.BASE_REVISION if activating else gate.TARGET_REVISION)
    monkeypatch.setattr(gate, "crt_table_count", lambda: 0)
    monkeypatch.setattr(gate, "checkpoint", lambda *args: calls.append("checkpoint"))
    monkeypatch.setattr(gate, "restore_checkpoint", lambda *args: calls.append("restore"))
    monkeypatch.setattr(gate, "atomic_current", lambda *args: calls.append("switch"))
    monkeypatch.setattr(gate, "production_op", lambda candidate, action: calls.append(action))
    gate.switch_with_schema(candidate if activating else gate.BASE, candidate, {}, {"clients": {}, "source_sha": "test"})
    expected = ["upgrade", "restore", "verify-active", "switch"] if activating else ["checkpoint", "downgrade", "verify-inactive", "switch"]
    positions = [calls.index(item) for item in expected]
    assert positions == sorted(positions)
    assert calls[0] == "quiesce" and calls[-1] == "resume"
    assert "import" not in calls


def test_stage_m_validator_requires_release_composition_marker(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("stage_m_marker", ROOT / "deploy/stage-m/validate_release_metadata.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.base, "validate", lambda _: None)
    with pytest.raises(ValueError, match="marker"):
        module.validate(tmp_path)
    marker = tmp_path / "services/ai-bridge/src/ai_bridge/stage_m_enabled"
    marker.parent.mkdir(parents=True)
    marker.touch()
    module.validate(tmp_path)
