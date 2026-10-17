"""SIMULATION only: CPU child lifecycle and existing N1 arbitration harness."""
from dataclasses import replace
import subprocess
from types import SimpleNamespace

import pytest

from ai_bridge.gateway.managed_worker_observer import Identity, WorkerObserver
from ai_bridge.gateway.accelerator_admission import AdmissionError
from test_accelerator_admission_n1 import SyntheticAdapter, claim, configuration, core


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRuntime:
    def __init__(self):
        self.original = Identity("boot", 123, 456, 123, 123, "attempt")
        self.current = self.original
        self.launch_error = None
        self.wait_result = 0
        self.spawns = 0
        self.waits = 0

    def spawn(self):
        self.spawns += 1
        if self.launch_error:
            raise self.launch_error
        return SimpleNamespace(pid=123)

    def identity(self, child, scope):
        if isinstance(self.current, BaseException):
            raise self.current
        return self.current

    def wait(self, child, timeout):
        self.waits += 1
        if isinstance(self.wait_result, BaseException):
            raise self.wait_result
        return self.wait_result


def observer(tmp_path):
    runtime = FakeRuntime()
    return WorkerObserver(tmp_path / "attempt", runtime=runtime), runtime


def test_clean_exit_is_only_process_closed_and_restart_is_forbidden(tmp_path):
    worker, runtime = observer(tmp_path)
    assert worker.start() == runtime.original
    with pytest.raises(RuntimeError):
        worker.start()
    assert worker.observe() == "PROCESS_CLOSED"
    assert worker.observe() == "PROCESS_CLOSED"
    assert runtime.waits == 1
    assert not hasattr(worker, "release") and not hasattr(worker, "verify")
    with pytest.raises(RuntimeError):
        worker.start()
    again = WorkerObserver(tmp_path / "attempt", runtime=runtime)
    with pytest.raises(FileExistsError):
        again.start()
    assert again.state == "DIRTY" and runtime.spawns == 1


@pytest.mark.parametrize("failure", ["spawn", "identity", "birth", "boot", "session", "group", "scope"])
def test_failed_start_pins_attempt(tmp_path, failure):
    worker, runtime = observer(tmp_path)
    if failure == "spawn":
        runtime.launch_error = OSError("failed launch")
    elif failure == "identity":
        runtime.current = FileNotFoundError("disappeared")
    else:
        changes = {"birth": {"birth_ticks": 0}, "boot": {"boot_id": ""},
                   "session": {"session": 124}, "group": {"process_group": 124},
                   "scope": {"scope": "other"}}
        runtime.current = replace(runtime.original, **changes[failure])
    with pytest.raises((OSError, RuntimeError)):
        worker.start()
    assert worker.state == "DIRTY"
    with pytest.raises(RuntimeError):
        worker.start()
    assert (tmp_path / "attempt").exists()


@pytest.mark.parametrize("failure", ["reuse", "boot", "scope", "missing", "crash", "unknown", "cancel", "timeout", "interrupted"])
def test_observation_uncertainty_never_clears_dirty(tmp_path, failure):
    worker, runtime = observer(tmp_path)
    worker.start()
    if failure == "reuse":
        runtime.current = replace(runtime.original, birth_ticks=999)
    elif failure == "boot":
        runtime.current = replace(runtime.original, boot_id="other-boot")
    elif failure == "scope":
        runtime.current = replace(runtime.original, scope="other")
    elif failure == "missing":
        runtime.current = FileNotFoundError("disappearance is not exit proof")
    elif failure == "crash":
        runtime.wait_result = -11
    elif failure == "unknown":
        runtime.wait_result = None
    elif failure == "cancel":
        worker.cancel()
    else:
        runtime.wait_result = (subprocess.TimeoutExpired("synthetic", .01)
                               if failure == "timeout" else KeyboardInterrupt())
    if failure in ("timeout", "interrupted"):
        with pytest.raises((subprocess.TimeoutExpired, KeyboardInterrupt)):
            worker.observe()
        runtime.wait_result = 0
    assert worker.observe() == "DIRTY"
    with pytest.raises(RuntimeError):
        worker.start()


def test_real_local_cpu_subprocess_smoke(tmp_path):
    worker = WorkerObserver(tmp_path / "cpu-smoke")
    try:
        identity = worker.start()
        assert identity.pid == identity.session == identity.process_group
        assert identity.birth_ticks > 0 and identity.boot_id
        assert worker.observe(timeout=3) == "PROCESS_CLOSED"
        assert str(identity.birth_ticks) in (tmp_path / "cpu-smoke").read_text()
    finally:
        # No signals: reap our finite CPU child even after a failed assertion.
        if worker.identity is not None:
            worker.observe(timeout=3)


def test_interrupted_identity_read_latches_dirty(tmp_path):
    worker, runtime = observer(tmp_path)
    worker.start()
    runtime.current = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        worker.observe()
    runtime.current = runtime.original
    assert worker.observe() == "DIRTY"


@pytest.mark.anyio
async def test_simulation_two_pools_shared_exclusive_and_no_exit_bypass(tmp_path):
    # Fake verified adapter lives only in tests, never in selectable production code.
    adapter = SyntheticAdapter()
    rm = core(tmp_path, adapter, config=configuration(2))
    try:
        for device in ("gpu-0", "gpu-1"):
            await rm.recover(device)
        for name in ("a", "b"):
            rm.submit(claim(name))
        a, b = await rm.wait("a"), await rm.wait("b")
        rm.submit(claim("x", mode="EXCLUSIVE"))
        rm.submit(claim("late"))
        rm.submit(claim("parallel", device=1, mode="EXCLUSIVE"))
        parallel = await rm.wait("parallel")
        assert rm.snapshot()["gpu-0"]["active"] == (a, b)
        assert parallel.resource_id != a.resource_id
        worker, _ = observer(tmp_path)
        worker.start()
        assert worker.observe() == "PROCESS_CLOSED"
        adapter.safe = False
        with pytest.raises(AdmissionError):
            await rm.release(a)
        assert rm.snapshot()["gpu-0"]["active"] == (a, b)
        assert rm.snapshot()["gpu-0"]["queued"] == ("x", "late")
        # Only explicit simulated device proof, not observer outcome, permits release.
        adapter.safe = True
        await rm.release(a)
        await rm.release(b)
        await rm.recover("gpu-0")  # Failed verification latched pool blocked.
        x = await rm.wait("x")
        assert rm.snapshot()["gpu-0"]["active"] == (x,)
        assert rm.snapshot()["gpu-1"]["active"] == (parallel,)
        await rm.release(x)
        await rm.release(await rm.wait("late"))
        await rm.release(parallel)
        assert all(not s["active"] and not s["queued"] for s in rm.snapshot().values())
    finally:
        rm.close()
