from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "deploy/stage-j/autopilot/gate.py"
SPEC = importlib.util.spec_from_file_location("stage_j_gate_recovery", MODULE_PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gate)


def test_recoverable_smoke_promotes_recovery_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "rollback-smoke-started.json").write_text("{}")
    observed: list[str] = []

    def fake_smoke(phase, *_args):
        observed.append(phase)
        (state / f"{phase}.json").write_text(json.dumps({
            "schema_version": 1,
            "release_id": "stage-i",
            "challenge": "recovery-challenge",
            "checks": {"health": True},
            "observability": {"status": "ok"},
            "knowledge": {"status": "absent_on_stage_i"},
            "time": 1,
            "services": [],
        }))

    monkeypatch.setattr(gate, "smoke", fake_smoke)
    gate.recoverable_smoke(
        "rollback-smoke", Path("/stage-i"), Path("/stage-j"),
        {}, {}, state,
    )

    assert observed and observed[0].startswith("rollback-smoke-recovery-")
    canonical = json.loads((state / "rollback-smoke.json").read_text())
    assert canonical["recovered_from"] == observed[0]
    assert canonical["challenge"] == "recovery-challenge"


def test_messaging_boundary_retry_waits_for_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    monkeypatch.setattr(gate.e, "hermes_state", lambda: None)
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")

    monkeypatch.setattr(gate.e, "messaging_boundary_smoke", flaky)
    gate.messaging_boundary_smoke_with_retry()
    assert attempts["count"] == 3


def test_messaging_boundary_retry_remains_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.e, "hermes_state", lambda: None)
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)

    def persistent():
        raise RuntimeError("persistent")

    monkeypatch.setattr(gate.e, "messaging_boundary_smoke", persistent)
    with pytest.raises(RuntimeError, match="persistent"):
        gate.messaging_boundary_smoke_with_retry()
