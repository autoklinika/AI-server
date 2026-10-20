"""CPU contract tests only. Mocked runtime evidence NEVER certifies real GPU."""
import asyncio
from dataclasses import replace
import sys

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.engine_state import ResourceState
from ai_bridge.gateway.vision_lifecycle import VisionCleanup, VisionSession
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers


@pytest.fixture
def anyio_backend():
    return "asyncio"


class CPUContractExecutor:
    resource_id = "local-primary"

    def __init__(self):
        self.enabled = True
        self.generation = "cpu-contract-generation-1"
        self.owner = self.session = None
        self.calls = []
        self.fail = None
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()
        self.hold = False
        self.cleanup_delta = {}
        self.real_child = False

    def available(self):
        return self.enabled

    async def step(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError("CPU injected failure")

    async def prepare(self, owner):
        await self.step("prepare")
        self.owner = owner
        self.session = VisionSession(self.generation, "cpu-contract-worker", self.resource_id)
        return self.session

    def verify(self, owner, session):
        return (owner == self.owner and session == self.session
                and session.generation == self.generation)

    async def inspect(self, owner, session, image_id):
        await self.step("inspect")
        self.entered.set()
        if self.hold:
            await self.resume.wait()
        if self.real_child:
            child = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-c", "print(sum(range(1000)))",
                stdout=asyncio.subprocess.PIPE)
            out, _ = await child.communicate()
            assert child.returncode == 0 and out.strip() == b"499500"
        return {"image_id": image_id, "execution_kind": "CPU_CONTRACT",
                "gpu_inference": "NOT_RUN"}

    async def cleanup(self, owner, session):
        await self.step("cleanup")
        return replace(VisionCleanup(owner, session, True, True, True, True), **self.cleanup_delta)


def make(tmp_path, runtime=None, **settings):
    providers = Providers()
    providers.models = []
    transport = httpx.MockTransport(providers.handle)
    app = create_gateway_app(
        Settings(_env_file=None, gateway_gpu_marker=tmp_path / "vision.dirty",
                 gateway_gpu_transition_timeout=.05, **settings),
        upstream_transport=transport, residency_transport=transport,
        vision_executor=runtime,
    )
    return app, providers


async def reserve(client):
    response = await client.post("/resource/leases", json={"workload": "vision-inspection"})
    assert response.status_code == 201
    return "/resource/leases/" + response.json()["lease_id"]


async def begin(client, path):
    response = await client.post(path + "/uses", json={
        "provider": "vision-local", "capability": "pcb-inspection"})
    assert response.status_code == 201, response.text
    return path + "/uses/" + response.json()["use_id"]


async def execute(client, use):
    return await client.post(use + "/inspect", json={"image_id": "pcb-calibration-1"})


async def assert_blocked(app, client, path):
    state = (await client.get("/status")).json()
    assert state["resource_manager"]["state"] == "BLOCKED"
    assert state["active_count"] == 1
    assert state["resource_leases"]["lease_count"] == 1
    assert state["resource_leases"]["leases"][0]["external_in_use"] is True
    assert state["resource_evidence"]["GPU_REUSE_SAFE"]["status"] == "NOT_VERIFIED"
    assert app.state.resource_leases.residency.marker.exists()
    assert (await client.delete(path)).json()["released"] is True
    assert (await app.state.resource_leases.snapshot())["lease_count"] == 1
    assert await app.state.resource_leases.reap_expired() == 0


@pytest.mark.anyio
async def test_default_unavailable_no_authority_from_descriptor_or_headers(tmp_path):
    app, providers = make(tmp_path)
    async with api_client(app) as client:
        status = (await client.get("/status")).json()
        assert status["resource_manager"]["engines"][2]["execution_available"] is False
        assert (await client.post("/resource/leases", json={"workload": "vision-inspection"})).status_code == 400
        response = await client.post("/resource/leases/no/uses", json={
            "provider": "vision-local", "capability": "pcb-inspection"},
            headers={"X-GPU-Grant": "approved", "X-GPU-Reuse-Safe": "true"})
        assert response.status_code == 400
        assert not providers.calls


@pytest.mark.anyio
async def test_optin_inventory_does_not_admit_disabled_executor(tmp_path):
    runtime = CPUContractExecutor()
    runtime.enabled = False
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        response = await client.post(path + "/uses", json={
            "provider": "vision-local", "capability": "pcb-inspection"})
        assert response.status_code == 400
        assert not runtime.calls
        assert not app.state.resource_leases.residency.marker.exists()
        assert (await client.get("/health")).json()["resource_manager"]["engines"][2]["status"] == "unavailable"
        await client.delete(path)


@pytest.mark.anyio
async def test_real_cpu_child_contract_and_normal_release(tmp_path):
    runtime = CPUContractExecutor()
    runtime.real_child = True
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        assert (await client.get(use)).status_code == 200
        state = (await client.get("/status")).json()
        assert state["resource_manager"]["state"] == "RUNNING"
        assert state["resource_manager"]["active_engine"] == "vision"
        assert state["registry"]["providers"][-1]["capabilities"] == ["pcb-inspection"]
        assert state["accelerators"]["provider_bindings"][-1]["accelerator_ids"] == ["local-primary"]
        assert state["active_count"] == 1
        response = await execute(client, use)
        assert response.status_code == 200
        assert response.json()["execution_kind"] == "CPU_CONTRACT"
        assert response.json()["gpu_inference"] == "NOT_RUN"
        assert (await execute(client, use)).status_code == 409
        await client.delete(path)
        assert (await client.delete(use)).json()["released"] is True
        state = (await client.get("/status")).json()
        assert state["resource_manager"]["state"] == "IDLE"
        assert state["active_count"] == state["resource_leases"]["lease_count"] == 0
        assert runtime.calls == ["prepare", "inspect", "cleanup"]
        assert not app.state.resource_leases.residency.marker.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("engine", ["ollama", "comfyui"])
async def test_switch_existing_engine_vision_existing_engine(tmp_path, engine):
    runtime = CPUContractExecutor()
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        async def previous():
            if engine == "ollama":
                assert (await client.post("/api/chat", json={"stream": False})).status_code == 200
            else:
                path = "/resource/leases/" + (await client.post("/resource/leases", json={
                    "workload": "media-image"})).json()["lease_id"]
                response = await client.post(path + "/uses", json={
                    "provider": "comfyui-local", "capability": "image-generation"})
                assert response.status_code == 201
                use = path + "/uses/" + response.json()["use_id"]
                await client.delete(path)
                assert (await client.delete(use)).json()["released"]
        await previous()
        path = await reserve(client)
        use = await begin(client, path)
        assert (await execute(client, use)).status_code == 200
        await client.delete(path)
        assert (await client.delete(use)).json()["released"]
        await previous()
        assert (await client.get("/health")).json()["resource_manager"]["state"] == "IDLE"


@pytest.mark.anyio
@pytest.mark.parametrize("bad", ["missing", "wrong-use", "wrong-lease", "wrong-workload"])
async def test_bad_owner_never_executes_or_releases(tmp_path, bad):
    runtime = CPUContractExecutor()
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        if bad == "missing":
            use = "/resource/leases/missing/uses/missing"
        elif bad == "wrong-workload":
            lid = (await client.post("/resource/leases", json={})).json()["lease_id"]
            path = "/resource/leases/" + lid
            assert (await client.post(path + "/uses", json={
                "provider": "vision-local", "capability": "pcb-inspection"})).status_code == 409
            use = path + "/uses/invalid"
        else:
            path = await reserve(client)
            use = await begin(client, path)
            use = (use.rsplit("/", 1)[0] + "/wrong" if bad == "wrong-use" else
                   use.replace(path, "/resource/leases/wrong"))
        assert (await execute(client, use)).status_code == 409
        assert "inspect" not in runtime.calls
        assert (await client.delete(use)).json()["released"] is False
        assert app.state.scheduler.admission_blocked is False


@pytest.mark.anyio
@pytest.mark.parametrize("image", ["../../etc/passwd", "/tmp/pcb.png", "http://host/image", "x;id", "", None, 1])
async def test_untrusted_paths_commands_urls_rejected(tmp_path, image):
    runtime = CPUContractExecutor()
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        response = await client.post(use + "/inspect", json={"image_id": image})
        assert response.status_code == 400
        assert runtime.calls == ["prepare"]
        assert app.state.scheduler.admission_blocked is False


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["prepare", "inspect", "cleanup"])
async def test_executor_failure_pins_and_survives_gateway_restart(tmp_path, phase):
    runtime = CPUContractExecutor()
    runtime.fail = phase
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        if phase == "prepare":
            assert (await client.post(path + "/uses", json={
                "provider": "vision-local", "capability": "pcb-inspection"})).status_code == 503
        else:
            use = await begin(client, path)
            if phase == "inspect":
                assert (await execute(client, use)).status_code == 503
            else:
                await execute(client, use)
                assert (await client.delete(use)).status_code == 503
        await assert_blocked(app, client, path)
    restarted, _ = make(tmp_path, runtime)
    async with api_client(restarted) as client:
        assert (await client.get("/status")).json()["resource_manager"]["state"] == "BLOCKED"
        assert (await execute(client, "/resource/leases/old/uses/old")).status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["job_terminal", "model_unloaded", "execution_closed", "release_authorized"])
@pytest.mark.parametrize("value", [False, 1, None])
async def test_cleanup_requires_all_trusted_predicates(tmp_path, field, value):
    runtime = CPUContractExecutor()
    runtime.cleanup_delta[field] = value
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        await execute(client, use)
        assert (await client.delete(use)).status_code == 503
        await assert_blocked(app, client, path)


@pytest.mark.anyio
async def test_restarted_executor_stale_generation_denies(tmp_path):
    runtime = CPUContractExecutor()
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        runtime.generation = "new-generation"
        assert (await client.get(use)).status_code == 409
        assert "inspect" not in runtime.calls
        await assert_blocked(app, client, path)


@pytest.mark.anyio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancel_keeps_owner_and_blocks(tmp_path, cancel):
    runtime = CPUContractExecutor()
    runtime.hold = True
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        adapter = next(iter(app.state.resource_leases._leases.values())).lifecycle
        adapter.timeout = .02 if not cancel else 3
        task = asyncio.create_task(execute(client, use))
        await runtime.entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).status_code == 503
        await assert_blocked(app, client, path)
        assert (await client.delete(use)).status_code == 503


@pytest.mark.anyio
async def test_no_parallel_execution_and_queued_lease_cannot_start(tmp_path):
    runtime = CPUContractExecutor()
    runtime.hold = True
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        queued = await reserve(client)
        assert (await client.post(queued + "/uses", json={
            "provider": "vision-local", "capability": "pcb-inspection"})).status_code == 409
        task = asyncio.create_task(execute(client, use))
        await runtime.entered.wait()
        assert (await execute(client, use)).status_code == 409
        assert (await client.delete(use)).status_code == 409
        assert (await app.state.scheduler.snapshot())["queued_count"] == 1
        runtime.resume.set()
        assert (await task).status_code == 200
        await client.delete(path)
        await client.delete(use)
        assert (await app.state.resource_leases.describe(queued.rsplit("/", 1)[-1]))["state"] == "active"
        assert runtime.calls.count("inspect") == 1


def test_four_states_only():
    assert set(ResourceState) == {"IDLE", "RUNNING", "SWITCHING", "BLOCKED"}


@pytest.mark.anyio
@pytest.mark.parametrize("identity", ["owner", "session"])
async def test_cleanup_wrong_identity_stays_blocked(tmp_path, identity):
    runtime = CPUContractExecutor()
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        await execute(client, use)
        runtime.cleanup_delta[identity] = (replace(runtime.owner, use_id="stale")
            if identity == "owner" else replace(runtime.session, generation="stale"))
        assert (await client.delete(use)).status_code == 503
        await assert_blocked(app, client, path)


@pytest.mark.anyio
async def test_remote_resource_never_bound_to_local_queue_executor(tmp_path):
    runtime = CPUContractExecutor()
    runtime.resource_id = "ventuno-gpu"
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        assert (await client.post(path + "/uses", json={
            "provider": "vision-local", "capability": "pcb-inspection"})).status_code == 400
        assert runtime.calls == []


@pytest.mark.anyio
async def test_release_while_prepared_without_job_completion_fails_closed(tmp_path):
    runtime = CPUContractExecutor()
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        assert (await client.delete(use)).status_code == 503
        await assert_blocked(app, client, path)


@pytest.mark.anyio
async def test_cancellation_after_cleanup_before_lease_finalization_is_durable(tmp_path):
    runtime = CPUContractExecutor()
    cleanup_entered, finish_cleanup = asyncio.Event(), asyncio.Event()
    original = runtime.cleanup

    async def cleanup(owner, session):
        cleanup_entered.set()
        await finish_cleanup.wait()
        return await original(owner, session)

    runtime.cleanup = cleanup
    app, _ = make(tmp_path, runtime)
    async with api_client(app) as client:
        path = await reserve(client)
        use = await begin(client, path)
        await execute(client, use)
        await client.delete(path)
        leases = app.state.resource_leases
        task = asyncio.create_task(client.delete(use))
        await cleanup_entered.wait()
        await leases._lock.acquire()
        try:
            finish_cleanup.set()
            for _ in range(100):
                if leases.residency.state == "llm":
                    break
                await asyncio.sleep(.001)
            assert leases.residency.state == "llm"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            leases._lock.release()
        await assert_blocked(app, client, path)
