"""Read-only / no-GPU tests for physical N1→N5 policy boundary."""
import json
from pathlib import Path

import pytest

from ai_bridge.gateway.n1_n5_rocm_probe import (
    ParkedROCmRuntime, run_denial_probe,
)
from ai_bridge.gateway.rocm_maintenance_pilot import PilotBlocked


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_real_parked_worker_is_denied_and_reaped(tmp_path):
    folder = tmp_path / "denial"
    record = await run_denial_probe(folder, preflight=lambda: {"safe": "NOT_VERIFIED"})
    assert record["n1"] == "BLOCKED_EXPECTED"
    assert record["n5"] == "PARKED_BEFORE_GPU"
    assert record["recovery"] == "DENIED_BY_N3"
    assert record["grant"] == "DENIED"
    assert record["gpu_execution"] == "DENIED"
    assert record["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert (folder / "n5-ownership.dirty").exists()
    assert "grant" not in [
        json.loads(line)["event"]
        for line in (folder / "n1-journal.jsonl").read_text().splitlines()]
    assert json.loads((folder / "gate-result.json").read_text()) == record
    with pytest.raises(PilotBlocked, match="already exists"):
        await run_denial_probe(folder, preflight=lambda: {})


@pytest.mark.anyio
async def test_preflight_failure_does_not_start_process_or_create_journal(tmp_path):
    def blocked():
        raise PilotBlocked("service still active")
    folder = tmp_path / "denial"
    with pytest.raises(PilotBlocked, match="service still active"):
        await run_denial_probe(folder, preflight=blocked)
    assert not folder.exists()


def test_untrusted_gpu_gate_cannot_be_activated():
    with pytest.raises(PilotBlocked, match="trusted E_safe"):
        ParkedROCmRuntime().activate(None)
