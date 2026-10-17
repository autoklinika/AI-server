"""N3 read-only observations, never GPU_REUSE_SAFE attestation.

No discovery on import, no admission wiring, no device opens/ioctls. Readers
must see the host proc/sys namespaces; even complete observations are racy and
cannot establish global ownership, isolation or inability to submit again.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, Mapping, Protocol, TypeVar
from uuid import UUID

from .accelerator_admission import Claim, Grant, Verification
from ai_bridge.providers.accelerators import AcceleratorDescriptor

T = TypeVar("T")


@dataclass(frozen=True)
class Observation(Generic[T]):
    status: Literal["OBSERVED", "UNKNOWN"]
    value: T | None
    reason: str = ""


class Reader(Protocol):
    def text(self, path: str) -> str: ...
    def realpath(self, path: str) -> str: ...
    def names(self, path: str) -> tuple[str, ...]: ...
    def device_number(self, path: str) -> tuple[int, int] | None: ...


class LocalReader:
    """Explicit opt-in, unprivileged metadata reads only; never open an FD target."""

    def text(self, path: str) -> str:
        return Path(path).read_text()

    def realpath(self, path: str) -> str:
        return str(Path(path).resolve(strict=True))

    def names(self, path: str) -> tuple[str, ...]:
        return tuple(os.listdir(path))

    def device_number(self, path: str) -> tuple[int, int] | None:
        info = os.stat(path)
        return (os.major(info.st_rdev), os.minor(info.st_rdev)) if stat.S_ISCHR(info.st_mode) else None


@dataclass(frozen=True)
class PciIdentity:
    boot_id: str
    sysfs_path: str
    bdf: str
    vendor: str
    device: str
    # No serial/UUID: identity of a PCI function in this boot, not persistent
    # hardware identity, nor proof that sibling functions are isolated cards.


@dataclass(frozen=True)
class DeviceHandle:
    fd: int
    number: tuple[int, int]
    kind: Literal["DRM", "KFD", "OTHER"]
    identity: Observation[PciIdentity]


@dataclass(frozen=True)
class ProcessSnapshot:
    epoch: str
    boot_id: str
    pid: int
    birth_ticks: int
    uids: tuple[int, int, int, int]  # real, effective, saved, filesystem
    cgroups: tuple[tuple[str, str, str], ...]  # hierarchy, controllers, pathname
    handles: tuple[DeviceHandle, ...]

    def matches(self, expected: ProcessSnapshot) -> bool:
        """Exact observation comparison, NOT a freshness or safety certificate."""
        return self == expected


_BDF = r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]"
_PCI_PATH = re.compile(rf"/sys/devices/pci[0-9a-f]{{4}}:[0-9a-f]{{2}}(?:/{_BDF})+")
_NODE = re.compile(r"(?:renderD[0-9]+|card[0-9]+)")
_BOOT = "/proc/sys/kernel/random/boot_id"


def birth_ticks(raw: str, pid: int) -> int:
    """stat comm may contain spaces, newlines and arbitrary parentheses."""
    prefix, sep, suffix = raw.rpartition(")")
    if not sep or not prefix.startswith(f"{pid} ("):
        raise ValueError("malformed stat identity")
    fields = suffix.split()  # field 3 (state) onwards; starttime is field 22
    if len(fields) < 20 or fields[0] not in tuple("RSDZTtXxKWIP"):
        raise ValueError("malformed stat fields")
    if not fields[19].isdigit() or int(fields[19]) <= 0:
        raise ValueError("invalid birth ticks")
    return int(fields[19])


class EvidenceCollector:
    def __init__(self, reader: Reader):
        self.reader = reader

    def _boot(self) -> str:
        raw = self.reader.text(_BOOT).strip()
        if str(UUID(raw)) != raw:
            raise ValueError("invalid boot ID")
        return raw

    def _pci(self, node_path: str, boot: str) -> PciIdentity:
        node = self.reader.realpath(node_path)
        if not _NODE.fullmatch(Path(node).name):
            raise ValueError("unexpected DRM node")
        path = self.reader.realpath(node_path + "/device")
        if (not _PCI_PATH.fullmatch(path)
                or node != path + "/drm/" + Path(node).name
                or self.reader.realpath(path + "/subsystem") != "/sys/bus/pci"
                or self.reader.realpath("/sys/bus/pci/devices/" + Path(path).name) != path):
            raise ValueError("unverified PCI layout or alias")
        vendor = self.reader.text(path + "/vendor").strip().lower()
        device = self.reader.text(path + "/device").strip().lower()
        if vendor not in {"0x1002", "0x8086", "0x10de"} or not re.fullmatch(r"0x[0-9a-f]{4}", device):
            raise ValueError("unsupported vendor or malformed PCI device")
        return PciIdentity(boot, path, Path(path).name, vendor, device)

    def devices(self, bindings: Mapping[str, tuple[str, ...]]) -> Observation[tuple[tuple[str, PciIdentity], ...]]:
        """Aliases within one logical card allowed; aliases across cards rejected.

        Binding paths refer to sysfs render nodes, including symlink aliases.
        Non-PCI and unverified layouts are deliberately unsupported.
        """
        try:
            boot = self._boot()
            result = []
            observed_paths = []
            seen = set()
            if not bindings:
                raise ValueError("missing bindings")
            for card, paths in bindings.items():
                if not card or not paths:
                    raise ValueError("missing card or paths")
                identities = set()
                for path in paths:
                    if not re.fullmatch(r"renderD[0-9]+", Path(self.reader.realpath(path)).name):
                        raise ValueError("binding must be a DRM render node")
                    identity = self._pci(path, boot)
                    identities.add(identity)
                    observed_paths.append((path, identity))
                if len(identities) != 1:
                    raise ValueError("ambiguous card binding")
                identity = identities.pop()
                if identity.bdf.rsplit(".", 1)[0] in seen:
                    raise ValueError("duplicate PCI device or sibling functions registered as distinct cards")
                seen.add(identity.bdf.rsplit(".", 1)[0])
                result.append((card, identity))
            if any(self._pci(path, boot) != identity for path, identity in observed_paths):
                raise ValueError("PCI binding changed")
            if self._boot() != boot:
                raise ValueError("boot changed")
            return Observation("OBSERVED", tuple(result))
        except (OSError, ValueError, RuntimeError) as exc:
            return Observation("UNKNOWN", None, str(exc))

    def _process_metadata(self, pid: int) -> tuple[int, tuple[int, ...], tuple[tuple[str, str, str], ...]]:
        base = f"/proc/{pid}"
        ticks = birth_ticks(self.reader.text(base + "/stat"), pid)
        uid_lines = [line.split()[1:] for line in self.reader.text(base + "/status").splitlines()
                     if line.startswith("Uid:")]
        if len(uid_lines) != 1 or len(uid_lines[0]) != 4 or not all(x.isdigit() for x in uid_lines[0]):
            raise ValueError("missing or malformed UID")
        groups = []
        for line in self.reader.text(base + "/cgroup").splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3 or not parts[0].isdigit() or not parts[2].startswith("/"):
                raise ValueError("malformed cgroup")
            groups.append(tuple(parts))
        if not groups or len({g[0] for g in groups}) != len(groups):
            raise ValueError("missing or ambiguous cgroup")
        return ticks, tuple(map(int, uid_lines[0])), tuple(sorted(groups))

    def _handles(self, pid: int, boot: str) -> tuple[DeviceHandle, ...]:
        base = f"/proc/{pid}/fd"
        names = self.reader.names(base)
        if any(not n.isdigit() for n in names):
            raise ValueError("malformed FD directory")
        handles = []
        for name in sorted(names, key=int):
            number = self.reader.device_number(base + "/" + name)
            if number is None:
                continue
            path = self.reader.realpath(f"/sys/dev/char/{number[0]}:{number[1]}")
            if path in ("/sys/devices/virtual/misc/kfd", "/sys/devices/virtual/kfd/kfd"):
                handles.append(DeviceHandle(int(name), number, "KFD", Observation(
                    "UNKNOWN", None, "KFD is global across AMD devices; no per-GPU binding")))
            elif _NODE.fullmatch(Path(path).name):
                handles.append(DeviceHandle(int(name), number, "DRM", Observation(
                    "OBSERVED", self._pci(path, boot))))
            else:
                # Includes proprietary NVIDIA handles: not silently ignored.
                handles.append(DeviceHandle(int(name), number, "OTHER", Observation(
                    "UNKNOWN", None, "unclassified character device")))
        if set(self.reader.names(base)) != set(names):
            raise ValueError("FD table changed")
        return tuple(handles)

    def process(self, pid: int, *, epoch: str) -> Observation[ProcessSnapshot]:
        try:
            if type(pid) is not int or pid <= 1 or not epoch:
                raise ValueError("invalid process or epoch")
            boot = self._boot()
            before = self._process_metadata(pid)
            handles = self._handles(pid, boot)
            if self._handles(pid, boot) != handles or self._process_metadata(pid) != before or self._boot() != boot:
                raise ValueError("process incarnation, scope, credentials, handles or boot changed")
            ticks, uids, groups = before
            return Observation("OBSERVED", ProcessSnapshot(epoch, boot, pid, ticks, uids, groups, handles))
        except (OSError, ValueError, RuntimeError) as exc:
            # Exit/EPERM is unknown, never evidence of an empty owner set.
            return Observation("UNKNOWN", None, str(exc))


class NonApprovingSafetyAdapter:
    """N1 Protocol shape only. No test-success flag, cache or production factory.

    Collector observations may be reviewed separately. Reading them here would
    add latency without providing the missing trusted global attestation.
    """
    adapter_id = "n3-evidence-only"

    def __init__(self, backend: Literal["rocm", "cuda", "vulkan", "cpu", "unknown"]):
        self.backend = backend

    def can_start(self, device: AcceleratorDescriptor, claim: Claim, active: tuple[Grant, ...]) -> bool:
        return False

    async def verify(self, challenge: Verification) -> bool:
        return False
