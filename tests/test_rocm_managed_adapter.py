"""CPU-only synthetic evidence; never import torch or run FIXED_COMMAND."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ai_bridge.gateway.managed_worker_observer import Identity, SyntheticCPU
from ai_bridge.gateway.rocm_managed_adapter import (
    Cleanup, FIXED_COMMAND, ProcDiagnostics, ROCmManagedAdapter,
)
from ai_bridge.gateway.rocm_test_worker import EXPECTED_PCI, WORKLOAD, run_fixed


class CPU:
    def __init__(self):
        self.current = Identity("boot", 123, 456, 123, 123, "attempt")
        self.code = 0
        self.spawns = 0
        self.raw = json.dumps(dict(schema=1, workload=WORKLOAD, pci_bdf=EXPECTED_PCI,
                                   local_synced=True, status="WORKER_LOCAL_SYNC"))

    def spawn(self):
        self.spawns += 1
        return SimpleNamespace(pid=123)

    def identity(self, child, scope):
        if isinstance(self.current, Exception):
            raise self.current
        return self.current

    def wait(self, child, timeout):
        if isinstance(self.code, Exception):
            raise self.code
        return self.code

    def result(self):
        return self.raw


class Diagnostics:
    def __init__(self):
        self.value = Cleanup("attempt", "boot", EXPECTED_PCI,
                             "CLEAR", "CLEAR", "CLEAR", "KNOWN")

    def collect(self, identity):
        return self.value


def setup(tmp_path, **kwargs):
    cpu, diagnostics = CPU(), Diagnostics()
    worker = ROCmManagedAdapter(tmp_path / "attempt", test_runtime=cpu,
                                diagnostics=diagnostics, **kwargs)
    return worker, cpu, diagnostics


def test_fixed_command_and_default_no_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("spawn"))
    assert FIXED_COMMAND == ("/opt/comfyui/venv/bin/python", "-I", str(
        Path(__file__).resolve().parents[1] / "src/ai_bridge/gateway/rocm_test_worker.py"))
    worker = ROCmManagedAdapter(tmp_path / "attempt")
    with pytest.raises(RuntimeError, match="blocked by policy"):
        worker.start()
    assert not (tmp_path / "attempt").exists()
    assert worker.gpu_admission == "NOT_ADMITTED"
    assert not hasattr(worker, "release") and not hasattr(worker, "can_start")


@pytest.mark.parametrize("workload", ["/bin/sh", "python", "", None, {}, "other"])
def test_no_arbitrary_workloads(tmp_path, workload):
    worker, cpu, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        worker.start(workload)
    assert cpu.spawns == 0


def test_local_success_never_global_safe_and_restart_duplicate_denied(tmp_path):
    worker, cpu, diagnostics = setup(tmp_path)
    worker.start()
    with pytest.raises(RuntimeError):
        worker.start()
    assert worker.observe() == "GPU_REUSE_SAFE_NOT_VERIFIED"
    assert worker.worker_status == "WORKER_LOCAL_SYNC"
    assert worker.gpu_admission == "NOT_ADMITTED"
    assert (tmp_path / "attempt").exists()
    again = ROCmManagedAdapter(tmp_path / "attempt", test_runtime=cpu, diagnostics=diagnostics)
    with pytest.raises(FileExistsError):
        again.start()
    assert cpu.spawns == 1


@pytest.mark.parametrize("field,value", [
    ("kfd", "LIVE"), ("kfd", "UNKNOWN"), ("drm", "LIVE"), ("drm", "UNKNOWN"),
    ("descendants", "LIVE"), ("descendants", "UNKNOWN"), ("owners", "UNKNOWN"),
    ("epoch", "stale"), ("boot_id", "old-boot"), ("pci_bdf", "0000:01:00.0"),
    ("kfd", "CLEANUP_PENDING"),
])
def test_exit_does_not_override_cleanup(tmp_path, field, value):
    worker, _, diagnostics = setup(tmp_path)
    worker.start()
    diagnostics.value = replace(diagnostics.value, **{field: value})
    assert worker.observe() == "DIRTY"
    diagnostics.value = Diagnostics().value
    assert worker.observe() == "DIRTY"
    assert worker.gpu_admission == "NOT_ADMITTED"


@pytest.mark.parametrize("failure", ["birth", "boot", "permission", "crash", "timeout", "cancel"])
def test_identity_and_lifecycle_latch(tmp_path, failure):
    worker, cpu, _ = setup(tmp_path)
    worker.start()
    original = cpu.current
    if failure == "birth":
        cpu.current = replace(original, birth_ticks=999)
    elif failure == "boot":
        cpu.current = replace(original, boot_id="old")
    elif failure == "permission":
        cpu.current = PermissionError()
    elif failure == "crash":
        cpu.code = -11
    elif failure == "timeout":
        cpu.code = subprocess.TimeoutExpired("CPU", .01)
    else:
        worker.cancel()
    assert worker.observe() == "DIRTY"
    cpu.current, cpu.code = original, 0
    assert worker.observe() == "DIRTY"


def test_delayed_cancel_during_observation(tmp_path):
    worker, cpu, _ = setup(tmp_path)
    worker.start()
    def finish(child, timeout):
        worker.cancel()
        return 0
    cpu.wait = finish
    assert worker.observe() == "DIRTY"
    assert worker.gpu_admission == "NOT_ADMITTED"


def test_delayed_cancel_during_spawn(tmp_path):
    worker, cpu, _ = setup(tmp_path)
    def spawn():
        worker.cancel()
        return SimpleNamespace(pid=123)
    cpu.spawn = spawn
    worker.start()
    assert worker.state == "DIRTY"
    assert worker.observe() == "DIRTY"


def test_delayed_cancel_during_cleanup(tmp_path):
    worker, _, diagnostics = setup(tmp_path)
    worker.start()
    def collect(identity):
        worker.cancel()
        return diagnostics.value
    diagnostics.collect = collect
    assert worker.observe() == "DIRTY"


@pytest.mark.parametrize("raw", ["{}", "[]", "null", "bad", "x" * 1025,
    '{"schema":1,"schema":1}', json.dumps(dict(schema=True, workload=WORKLOAD,
    pci_bdf=EXPECTED_PCI, local_synced=True, status="WORKER_LOCAL_SYNC")),
    json.dumps({**json.loads(CPU().raw), "global_safe": True}),
    json.dumps({**json.loads(CPU().raw), "local_synced": 1})])
def test_malformed_result(tmp_path, raw):
    worker, cpu, _ = setup(tmp_path)
    worker.start()
    cpu.raw = raw
    assert worker.observe() == "DIRTY"


@pytest.mark.parametrize("mode", ["SHARED", "EXCLUSIVE"])
def test_known_owner_diagnostics_allowed_but_never_admitted(tmp_path, mode):
    worker, _, _ = setup(tmp_path, mode=mode)
    worker.start()
    assert worker.observe() == "GPU_REUSE_SAFE_NOT_VERIFIED"
    assert worker.gpu_admission == "NOT_ADMITTED"


def test_readonly_proc_permission_denied_is_unknown(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError()
    monkeypatch.setattr(Path, "read_text", denied)
    result = ProcDiagnostics().collect(CPU().current)
    assert (result.kfd, result.drm, result.descendants, result.owners) == ("UNKNOWN",) * 4


@pytest.mark.parametrize("failure", [None, "unknown-owner", "live-kfd", "missing-kfd",
    "stale-drm", "stale-boot", "stale-process", "descendant"])
def test_proc_diagnostics_synthetic_host(monkeypatch, failure):
    from ai_bridge.gateway import rocm_managed_adapter as module
    from ai_bridge.gateway.accelerator_evidence import Observation
    pci = SimpleNamespace(boot_id="old" if failure == "stale-drm" else "boot",
                          bdf=EXPECTED_PCI)
    snapshot = SimpleNamespace(boot_id="old" if failure == "stale-boot" else "boot",
        epoch="attempt", birth_ticks=789, handles=(SimpleNamespace(
            kind="DRM", identity=Observation("OBSERVED", pci)),))
    class Reader:
        def names(self, path):
            if path == "/proc":
                return ("7934",)
            if failure == "missing-kfd":
                raise FileNotFoundError()
            return ("7934", "123") if failure == "live-kfd" else ("7934",)
        def text(self, path):
            if path.endswith("boot_id"):
                return "boot"
            fields = ["S", "1", "7934", "123" if failure == "descendant" else "7934"] + ["0"] * 15 + ["789"]
            return "7934 (comfy) " + " ".join(fields)
    class Collector:
        def __init__(self, reader):
            self.calls = 0
        def process(self, pid, *, epoch):
            self.calls += 1
            if failure == "stale-process" and self.calls > 1:
                return Observation("UNKNOWN", None)
            return Observation("OBSERVED", snapshot)
    monkeypatch.setattr(module, "LocalReader", Reader)
    monkeypatch.setattr(module, "EvidenceCollector", Collector)
    monkeypatch.setattr(Path, "read_text", lambda p: "0x1002" if p.name == "vendor" else "0x150e")
    known = frozenset() if failure == "unknown-owner" else frozenset({("boot", 7934, 789)})
    result = ProcDiagnostics(known_owners=known).collect(CPU().current)
    statuses = (result.kfd, result.drm, result.descendants, result.owners)
    if failure is None:
        assert statuses == ("CLEAR", "CLEAR", "CLEAR", "KNOWN")
    else:
        assert statuses != ("CLEAR", "CLEAR", "CLEAR", "KNOWN")


def test_actual_cpu_child_only(tmp_path):
    class LocalCPU(SyntheticCPU):
        def result(self):
            return CPU().raw
    class LocalDiagnostics:
        def collect(self, identity):
            return Cleanup(identity.scope, identity.boot_id, EXPECTED_PCI,
                           "CLEAR", "CLEAR", "CLEAR", "KNOWN")
    worker = ROCmManagedAdapter(tmp_path / "attempt", test_runtime=LocalCPU(),
                                diagnostics=LocalDiagnostics())
    worker.start()
    assert worker.observe(timeout=3) == "GPU_REUSE_SAFE_NOT_VERIFIED"
    assert worker.gpu_admission == "NOT_ADMITTED"


class FakeTorch:
    def __init__(self):
        self.calls = []
        self.version = SimpleNamespace(hip="test-only")
        self.props = SimpleNamespace(pci_bus_id=EXPECTED_PCI, gcnArchName="gfx1150")
        self.cuda = SimpleNamespace(device_count=lambda: 1,
            get_device_properties=lambda i: self.props,
            set_device=lambda i: self.calls.append(("set", i)),
            synchronize=lambda i: self.calls.append(("sync", i)),
            empty_cache=lambda: self.calls.append(("empty",)))
        self.float32 = "float32"

    def ones(self, shape, **kwargs):
        self.calls.append(("ones", shape, kwargs))
        return 1

    def matmul(self, a, b):
        self.calls.append(("matmul",))
        return 64

    def all(self, value):
        return SimpleNamespace(item=lambda: value)


def test_fixed_payload_order_cpu_mock(tmp_path):
    pci = tmp_path / EXPECTED_PCI
    pci.mkdir()
    (pci / "vendor").write_text("0x1002")
    (pci / "device").write_text("0x150e")
    torch = FakeTorch()
    assert run_fixed(torch, pci_root=tmp_path) == json.loads(CPU().raw)
    assert [c[0] for c in torch.calls] == ["set", "ones", "ones", "matmul", "sync", "empty", "sync"]
    assert torch.calls[1][1:] == ((64, 64), dict(device="cuda:0", dtype="float32"))


def test_payload_failure_still_attempts_local_cleanup(tmp_path):
    pci = tmp_path / EXPECTED_PCI
    pci.mkdir()
    (pci / "vendor").write_text("0x1002")
    (pci / "device").write_text("0x150e")
    torch = FakeTorch()
    def fail(*args):
        raise RuntimeError("synthetic kernel failure")
    torch.matmul = fail
    with pytest.raises(RuntimeError, match="synthetic kernel failure"):
        run_fixed(torch, pci_root=tmp_path)
    assert torch.calls[-2:] == [("empty",), ("sync", 0)]


@pytest.mark.parametrize("failure", ["hip", "count", "arch", "pci", "missing-pci", "sysfs"])
def test_payload_binding_fail_closed_cpu_mock(tmp_path, failure):
    torch = FakeTorch()
    if failure == "hip":
        torch.version.hip = None
    elif failure == "count":
        torch.cuda.device_count = lambda: 2
    elif failure == "arch":
        torch.props.gcnArchName = "other"
    elif failure == "pci":
        torch.props.pci_bus_id = "0000:01:00.0"
    elif failure == "missing-pci":
        del torch.props.pci_bus_id
    with pytest.raises((RuntimeError, OSError)):
        run_fixed(torch, pci_root=tmp_path)
    assert torch.calls == []



def test_hip_pci_binding_fallback_when_torch_field_absent(tmp_path):
    pci = tmp_path / EXPECTED_PCI
    pci.mkdir()
    (pci / "vendor").write_text("0x1002")
    (pci / "device").write_text("0x150e")
    torch = FakeTorch()
    del torch.props.pci_bus_id
    calls = []
    def hip_binding(torch_object):
        calls.append(torch_object)
        return EXPECTED_PCI
    assert run_fixed(torch, pci_root=tmp_path, hip_bus_id=hip_binding)["local_synced"] is True
    assert calls == [torch]


def test_hip_pci_fallback_rejects_wrong_device(tmp_path):
    torch = FakeTorch()
    del torch.props.pci_bus_id
    with pytest.raises(RuntimeError, match="wrong runtime PCI binding"):
        run_fixed(torch, pci_root=tmp_path, hip_bus_id=lambda _: "0000:01:00.0")
    assert torch.calls == []


def test_documented_hip_pci_abi_reads_bound_ordinal(monkeypatch, tmp_path):
    import ctypes
    from ai_bridge.gateway.rocm_test_worker import _hip_bus_id
    package = tmp_path / "site-packages"
    (package / "torch").mkdir(parents=True)
    lib = package / "_rocm_sdk_core" / "lib" / "libamdhip64.so.7"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"test-double")
    torch = SimpleNamespace(__file__=str(package / "torch" / "__init__.py"))
    observed = []
    class FakeFn:
        def __call__(self, buffer, size, ordinal):
            observed.append((size, ordinal))
            ctypes.memmove(buffer, b"0000:c6:00.0\x00", 13)
            return 0
    monkeypatch.setattr(ctypes, "CDLL", lambda _: SimpleNamespace(hipDeviceGetPCIBusId=FakeFn()))
    assert _hip_bus_id(torch) == EXPECTED_PCI
    assert observed == [(64, 0)]


def test_documented_hip_pci_abi_failure_is_denied(monkeypatch, tmp_path):
    import ctypes
    from ai_bridge.gateway.rocm_test_worker import _hip_bus_id
    package = tmp_path / "site-packages"
    (package / "torch").mkdir(parents=True)
    lib = package / "_rocm_sdk_core" / "lib" / "libamdhip64.so.7"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"test-double")
    torch = SimpleNamespace(__file__=str(package / "torch" / "__init__.py"))
    class FakeFn:
        def __call__(self, buffer, size, ordinal):
            return 101
    monkeypatch.setattr(ctypes, "CDLL", lambda _: SimpleNamespace(hipDeviceGetPCIBusId=FakeFn()))
    with pytest.raises(RuntimeError, match="lookup failed"):
        _hip_bus_id(torch)
