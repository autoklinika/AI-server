"""DEV diagnostic supervisor; no GPU launch authority or scheduler release API.

Only trusted in-process CPU test injection can spawn. The fixed real command
is a specification for a future authorized adapter, not an executable option.
Durable N5 tombstones retain attempt ownership even on success. Scope/session
are labels, not containment; proc/sys observations are racy, not attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol

from .accelerator_evidence import EvidenceCollector, LocalReader
from .managed_worker_observer import Identity, Runtime, WorkerObserver
from .rocm_test_worker import EXPECTED_PCI, WORKLOAD

FIXED_COMMAND = ("/opt/comfyui/venv/bin/python", "-I",
                 str(Path(__file__).with_name("rocm_test_worker.py").resolve()))


@dataclass(frozen=True)
class Cleanup:
    epoch: str
    boot_id: str
    pci_bdf: str
    kfd: str = "UNKNOWN"
    drm: str = "UNKNOWN"
    descendants: str = "UNKNOWN"
    owners: str = "UNKNOWN"


class TestRuntime(Runtime, Protocol):
    def result(self) -> str: ...


class ProcDiagnostics:
    """Read-only host diagnostics. Unreadable/disappearing entries => UNKNOWN.

    Known owner keys must originate from trusted preflight, never worker JSON.
    A known ComfyUI FD owner may remain; this does not authorize SHARED use.
    Escaped descendants, transferred FDs and submissions outside this namespace
    cannot be excluded by this scan, even if all fields say CLEAR.
    """

    def __init__(self, *, known_owners: frozenset[tuple[str, int, int]] = frozenset()):
        self.known_owners = known_owners

    def collect(self, identity: Identity) -> Cleanup:
        values = dict(epoch=identity.scope, boot_id=identity.boot_id, pci_bdf=EXPECTED_PCI)
        try:
            reader = LocalReader()
            collector = EvidenceCollector(reader)
            boot = reader.text("/proc/sys/kernel/random/boot_id").strip()
            if boot != identity.boot_id:
                return Cleanup(**{**values, "boot_id": boot})
            pci = Path("/sys/bus/pci/devices") / EXPECTED_PCI
            if ((pci / "vendor").read_text().strip() != "0x1002"
                    or (pci / "device").read_text().strip() != "0x150e"):
                return Cleanup(**{**values, "pci_bdf": "UNKNOWN"})
            # This optional kernel interface must actually be observed. Missing
            # interface is UNKNOWN, never inferred clear from child exit.
            kfd = reader.names("/sys/class/kfd/kfd/proc")
            pids = tuple(n for n in reader.names("/proc") if n.isdigit())
            drm = descendants = "CLEAR"
            owners = "KNOWN"
            known_pids = set()
            for raw in pids:
                pid = int(raw)
                if pid <= 1:
                    # N3 intentionally excludes init; cannot certify its FDs.
                    owners = "UNKNOWN"
                    continue
                observed = collector.process(pid, epoch=identity.scope)
                if observed.status != "OBSERVED":
                    return Cleanup(**values)
                process = observed.value
                if process.boot_id != boot or process.epoch != identity.scope:
                    return Cleanup(**values)
                fields = reader.text(f"/proc/{pid}/stat").rsplit(")", 1)[1].split()
                if int(fields[19]) != process.birth_ticks:
                    return Cleanup(**values)
                owned = (pid == identity.pid or int(fields[3]) == identity.session
                         or int(fields[1]) == identity.pid)
                if owned:
                    descendants = "LIVE"
                key = (process.boot_id, pid, process.birth_ticks)
                known = key in self.known_owners
                if known:
                    known_pids.add(raw)
                for handle in process.handles:
                    if handle.kind == "DRM" and (
                            handle.identity.status != "OBSERVED"
                            or handle.identity.value.boot_id != boot
                            or handle.identity.value.bdf != EXPECTED_PCI):
                        return Cleanup(**values)
                    if owned and handle.kind == "DRM":
                        drm = "LIVE"
                    if handle.kind == "OTHER" or (not owned and not known):
                        owners = "UNKNOWN"
                if collector.process(pid, epoch=identity.scope) != observed:
                    return Cleanup(**values)
            if (set(reader.names("/sys/class/kfd/kfd/proc")) != set(kfd)
                    or set(n for n in reader.names("/proc") if n.isdigit()) != set(pids)
                    or reader.text("/proc/sys/kernel/random/boot_id").strip() != boot):
                return Cleanup(**values)
            kfd_status = "CLEAR" if set(kfd) <= known_pids else "LIVE"
            return Cleanup(**values, kfd=kfd_status, drm=drm,
                           descendants=descendants, owners=owners)
        except (OSError, ValueError, IndexError, RuntimeError):
            return Cleanup(**values)


class ROCmManagedAdapter:
    gpu_admission = "NOT_ADMITTED"
    gpu_status = "GPU_REUSE_SAFE_NOT_VERIFIED"

    def __init__(self, marker: Path, *, test_runtime: TestRuntime | None = None,
                 diagnostics: ProcDiagnostics | None = None, mode: str = "EXCLUSIVE"):
        if mode not in ("SHARED", "EXCLUSIVE"):
            raise ValueError("invalid mode")
        self._runtime = test_runtime
        self._observer = WorkerObserver(marker, runtime=test_runtime)
        self._diagnostics = diagnostics if diagnostics is not None else ProcDiagnostics()
        self.mode = mode
        self._cancelled = False
        self.state = "BLOCKED_BY_POLICY" if test_runtime is None else "NEW"
        self.cleanup = None
        self.worker_status = "NOT_OBSERVED"

    @property
    def state(self):
        return "DIRTY" if self._cancelled else self._state

    @state.setter
    def state(self, value):
        self._state = value

    def start(self, workload: str = WORKLOAD) -> Identity:
        if type(workload) is not str or workload != WORKLOAD:
            raise ValueError("only the fixed ROCm workload is allowlisted")
        if self._runtime is None:
            raise RuntimeError("real GPU launch blocked by policy; NOT_ADMITTED")
        if self.state != "NEW":
            raise RuntimeError("attempt already owned or dirty")
        self.state = "DIRTY"
        identity = self._observer.start()
        if self._cancelled:
            self._observer.cancel()
        self.state = "RUNNING"
        return identity

    def cancel(self):
        self._cancelled = True
        self._observer.cancel()
        self.state = "DIRTY"

    def observe(self, *, timeout: float = 2.0) -> str:
        was_running = self.state == "RUNNING"
        self.state = "DIRTY"
        try:
            closed = self._observer.observe(timeout=timeout)
            # Worker JSON is untrusted local telemetry, not cleanup evidence.
            raw = self._runtime.result()
            expected = {"schema": 1, "workload": WORKLOAD, "pci_bdf": EXPECTED_PCI,
                        "local_synced": True, "status": "WORKER_LOCAL_SYNC"}
            if type(raw) is not str or len(raw) > 1024:
                raise ValueError("invalid worker result")
            def unique(pairs):
                result = dict(pairs)
                if len(result) != len(pairs):
                    raise ValueError("duplicate result fields")
                return result
            result = json.loads(raw, object_pairs_hook=unique)
            if (result != expected or type(result.get("schema")) is not int
                    or result.get("local_synced") is not True):
                raise ValueError("invalid worker result")
            self.cleanup = self._diagnostics.collect(self._observer.identity)
            c = self.cleanup
            identity = self._observer.identity
            if (was_running and not self._cancelled and closed == "PROCESS_CLOSED"
                    and self._observer.state == "PROCESS_CLOSED"
                    and (c.epoch, c.boot_id, c.pci_bdf) ==
                        (identity.scope, identity.boot_id, EXPECTED_PCI)
                    and (c.kfd, c.drm, c.descendants, c.owners) ==
                        ("CLEAR", "CLEAR", "CLEAR", "KNOWN")):
                self.worker_status = "WORKER_LOCAL_SYNC"
                self.state = "GPU_REUSE_SAFE_NOT_VERIFIED"
        except Exception:
            self.state = "DIRTY"
        return self.state
