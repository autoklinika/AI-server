"""Fail-closed GPU device-client inventory, independent of GPU hardware."""
import pytest
from ai_bridge.gateway.admission import binding
from test_vision_rm_failure_matrix_dev import fixture_rm, admit


@pytest.fixture
def anyio_backend():return "asyncio"


@pytest.mark.anyio
async def test_missing_cross_uid_gpu_inventory_denies_admission(tmp_path):
    prov,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    gpu.vision_strict_gpu_clients=True
    gpu.vision_clients_probe=lambda:None
    from ai_bridge.gateway.jobs import JobMetadata
    from ai_bridge.gateway.admission import external_workload
    lease=await leases.create(priority=200,source="no-evidence",
        metadata=JobMetadata(workload=external_workload(reg,"vision-benchmark")))
    with pytest.raises(Exception,match="GPU client evidence unavailable"):
        await leases.begin_external_use(lease["lease_id"],binding(reg,"vision-local","image-analysis"),
                                        worker_pid=222,scope_path="test-scope")
    assert scheduler.admission_blocked and gpu.marker.is_file()
    assert gpu.state=="blocked"
    await client.aclose()


@pytest.mark.anyio
async def test_new_gpu_client_after_worker_exit_blocks_release(tmp_path):
    prov,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    gpu.vision_strict_gpu_clients=True
    observations=iter([
        frozenset({(3005,101)}),
        frozenset({(3005,101),(5555,202)})
    ])
    gpu.vision_clients_probe=lambda: next(observations)
    lease,use=await admit(leases,reg)
    state.update(birth=None,members=set())
    with pytest.raises(Exception,match="new GPU device client"):
        await leases.end_external_use(lease["lease_id"],use)
    assert scheduler.admission_blocked and gpu.marker.exists()
    await client.aclose()


@pytest.mark.anyio
async def test_stable_gpu_client_inventory_can_release(tmp_path):
    prov,state,client,gpu,scheduler,leases,reg=fixture_rm(tmp_path)
    gpu.vision_strict_gpu_clients=True
    gpu.vision_clients_probe=lambda:frozenset({(3005,101)})
    lease,use=await admit(leases,reg)
    state.update(birth=None,members=set())
    assert await leases.end_external_use(lease["lease_id"],use)
    assert gpu.state=="llm" and not gpu.marker.exists()
    await leases.release(lease["lease_id"])
    await client.aclose()
