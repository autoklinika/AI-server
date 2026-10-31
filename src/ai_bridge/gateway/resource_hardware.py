"""Linux GPU/host-memory observation for P2-A2 (no execution authority).

A driver memory counter is NOT an RM reservation, quiescence proof or a P1
MemoryObservation. AMD's reported VRAM and /proc/meminfo must not be combined
without separately validated memory-domain mapping and allocation provenance.

Only explicit one-shot calls perform I/O. Nothing probes devices on import.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

_MI_B = 1024 * 1024
_NVIDIA_QUERY = (
    "/usr/bin/nvidia-smi",
    "--query-gpu=index,uuid,pci.bus_id,memory.total,memory.used",
    "--format=csv,noheader,nounits",
)
_BDF = re.compile(r"(?i)(?:[0-9a-f]{4}|[0-9a-f]{8}):[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")
_CARD = re.compile(r"card[0-9]+")
_GPU_UUID = re.compile(r"GPU-[a-zA-Z0-9-]{8,128}")
_BOOT_ID = re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_MAX_SAMPLE = 16 * 1024


@dataclass(frozen=True, slots=True)
class GpuReading:
    vendor: Literal["nvidia", "amd"]
    identity: str
    identity_source: Literal["driver_uuid", "boot_pci"]
    pci_bdf: str
    memory_scope: Literal["dedicated_vram", "amd_driver_vram_unclassified"]
    total_bytes: int | None
    used_bytes: int | None


@dataclass(frozen=True, slots=True)
class HostReading:
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True, slots=True)
class HardwareReading:
    boot_id: str | None
    observed_at_ns: int
    devices: tuple[GpuReading, ...]
    host: HostReading | None
    issues: tuple[str, ...]
    # Always false. There is no trusted hardware->RM lease attribution in P2-A2.
    authorizes_execution: Literal[False] = False


def _bdf(raw: str) -> str:
    value = raw.strip().lower()
    if not _BDF.fullmatch(value):
        raise ValueError("invalid pci address")
    if len(value.split(":")[0]) == 8:
        domain, rest = value.split(":", 1)
        if any(c != "0" for c in domain[:4]):
            raise ValueError("noncanonical PCI domain")
        return f"{domain[4:]}:{rest}"
    return value


def parse_nvidia_csv(raw: str) -> tuple[GpuReading, ...]:
    """Parse the exact NVIDIA query (MiB counters), rejecting ambiguous rows."""
    if not isinstance(raw, str) or len(raw) > _MAX_SAMPLE:
        raise ValueError("oversized NVIDIA response")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 32:
        raise ValueError("too many GPU devices")
    seen_ids: set[str] = set()
    seen_bus: set[str] = set()
    seen_ordinals: set[int] = set()
    result: list[GpuReading] = []
    for line in lines:
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 5:
            raise ValueError("invalid NVIDIA row")
        ordinal, uuid, bus, total, used = fields
        if not ordinal.isascii() or not ordinal.isdecimal():
            raise ValueError("invalid NVIDIA ordinal")
        index = int(ordinal)
        if not _GPU_UUID.fullmatch(uuid):
            raise ValueError("invalid NVIDIA UUID")
        canonical_bus = _bdf(bus)
        if not total.isascii() or not total.isdecimal():
            raise ValueError("invalid NVIDIA total MiB")
        if not used.isascii() or not used.isdecimal():
            raise ValueError("invalid NVIDIA used MiB")
        total_bytes, used_bytes = int(total) * _MI_B, int(used) * _MI_B
        if total_bytes <= 0 or used_bytes > total_bytes:
            raise ValueError("invalid NVIDIA memory")
        if uuid in seen_ids or canonical_bus in seen_bus or index in seen_ordinals:
            raise ValueError("duplicate NVIDIA identity")
        seen_ids.add(uuid)
        seen_bus.add(canonical_bus)
        seen_ordinals.add(index)
        result.append(
            GpuReading(
                vendor="nvidia",
                identity=uuid,
                identity_source="driver_uuid",
                pci_bdf=canonical_bus,
                memory_scope="dedicated_vram",
                total_bytes=total_bytes,
                used_bytes=used_bytes,
            )
        )
    return tuple(sorted(result, key=lambda item: item.identity))


def parse_meminfo(raw: str) -> HostReading:
    """Read MemTotal/MemAvailable in KiB, not a GPU/UMA allocation budget."""
    if not isinstance(raw, str) or len(raw) > 16 * 1024:
        raise ValueError("invalid meminfo")
    found: dict[str, int] = {}
    for line in raw.splitlines():
        field, sep, value = line.partition(":")
        if not sep or field not in ("MemTotal", "MemAvailable"):
            continue
        if field in found:
            raise ValueError("duplicate memory key")
        match = re.fullmatch(r"\s*([0-9]+) kB\s*", value)
        if match is None:
            raise ValueError("invalid memory units")
        found[field] = int(match.group(1)) * 1024
    total = found.get("MemTotal", 0)
    available = found.get("MemAvailable", -1)
    if not 0 <= available <= total or total == 0:
        raise ValueError("missing or invalid host memory")
    return HostReading(total_bytes=total, available_bytes=available)


def _bounded_read(path: Path, *, limit: int = 16 * 1024) -> str:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("oversized read-only system file")
    return data.decode("ascii")


def _sysfs_bytes(path: Path) -> int | None:
    try:
        text = _bounded_read(path, limit=64).strip()
    except OSError:
        return None
    if not text.isascii() or not text.isdecimal():
        return None
    return int(text)


def read_amd_drm(drm_root: Path) -> tuple[GpuReading, ...]:
    """Observe AMD DRM cards by PCI function; no inference that VRAM equals RAM."""
    seen_bus: set[str] = set()
    results: list[GpuReading] = []
    for card in sorted(drm_root.iterdir(), key=lambda item: item.name):
        if not _CARD.fullmatch(card.name):
            continue  # Ignore card0-DP-1 etc; they are DRM connectors.
        device = card / "device"
        try:
            vendor = _bounded_read(device / "vendor", limit=16).strip().lower()
        except OSError:
            continue  # A missing vendor on a non-AMD card is not AMD evidence.
        if vendor != "0x1002":
            continue
        try:
            pci = _bdf(device.resolve(strict=True).name)
        except (ValueError, OSError):
            raise ValueError("invalid AMD PCI identity") from None
        if pci in seen_bus:
            raise ValueError("duplicate AMD PCI identity")
        seen_bus.add(pci)
        total = _sysfs_bytes(device / "mem_info_vram_total")
        used = _sysfs_bytes(device / "mem_info_vram_used")
        if total is None or total == 0 or used is None or used > total:
            total = used = None  # An invalid counter must never be treated as free.
        results.append(
            GpuReading(
                vendor="amd",
                identity=f"boot-pci:{pci}",
                identity_source="boot_pci",
                pci_bdf=pci,
                memory_scope="amd_driver_vram_unclassified",
                total_bytes=total,
                used_bytes=used,
            )
        )
    return tuple(sorted(results, key=lambda item: item.pci_bdf))


def _run_nvidia_query() -> str:
    completed = subprocess.run(
        _NVIDIA_QUERY,
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    if completed.returncode != 0:
        raise OSError("NVIDIA driver query failed")
    return completed.stdout


def collect_linux_hardware(
    *,
    nvidia_query: Callable[[], str] = _run_nvidia_query,
    drm_root: Path = Path("/sys/class/drm"),
    proc_meminfo: Path = Path("/proc/meminfo"),
    proc_boot_id: Path = Path("/proc/sys/kernel/random/boot_id"),
    expected_nvidia: int | None = None,
    expected_amd: int | None = None,
    expected_nvidia_uuids: tuple[str, ...] = (),
    now_ns: Callable[[], int] = time.monotonic_ns,
) -> HardwareReading:
    """Explicit read-only sample. Do NOT call from an admission/cleanup path.

    Expected counts/UUIDs are operator declarations, not proof of completeness.
    sysfs reports AMD driver VRAM; it might be a BIOS carveout, not shared RAM.
    """
    for count in (expected_nvidia, expected_amd):
        if count is not None and (type(count) is not int or count < 0 or count > 32):
            raise ValueError("invalid expected device count")
    if len(expected_nvidia_uuids) != len(set(expected_nvidia_uuids)):
        raise ValueError("duplicate expected UUID")
    if len(expected_nvidia_uuids) > 32 or any(
        not _GPU_UUID.fullmatch(value) for value in expected_nvidia_uuids
    ):
        raise ValueError("invalid expected UUID")

    issues: set[str] = set()
    boot: str | None = None
    try:
        value = _bounded_read(proc_boot_id, limit=80).strip()
        if _BOOT_ID.fullmatch(value):
            boot = value.lower()
        else:
            issues.add("boot_epoch_unavailable")
    except (OSError, UnicodeError, ValueError):
        issues.add("boot_epoch_unavailable")

    host: HostReading | None = None
    try:
        host = parse_meminfo(_bounded_read(proc_meminfo))
    except (OSError, UnicodeError, ValueError):
        issues.add("host_memory_unavailable")

    try:
        nvidia = parse_nvidia_csv(nvidia_query())
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        issues.add("nvidia_observation_unavailable")
        nvidia = ()
    try:
        amd = read_amd_drm(drm_root)
    except (OSError, UnicodeError, ValueError):
        issues.add("amd_observation_unavailable")
        amd = ()

    if expected_nvidia is not None and len(nvidia) != expected_nvidia:
        issues.add("nvidia_count_mismatch")
    if expected_amd is not None and len(amd) != expected_amd:
        issues.add("amd_count_mismatch")
    if expected_nvidia_uuids and set(expected_nvidia_uuids) != {
        item.identity for item in nvidia
    }:
        issues.add("nvidia_identity_mismatch")

    identities = [d.pci_bdf for d in (*nvidia, *amd)]
    if len(identities) != len(set(identities)):
        issues.add("duplicate_cross_vendor_pci")
    if any(item.total_bytes is None for item in amd):
        issues.add("amd_counters_unavailable")

    # Reported AMD VRAM is not necessarily the CPU's MemTotal. No inference
    # about shared/free memory or RM ownership is valid from these readings.
    return HardwareReading(
        boot_id=boot,
        observed_at_ns=now_ns(),
        devices=tuple(sorted((*nvidia, *amd), key=lambda item: (item.vendor, item.identity))),
        host=host,
        issues=tuple(sorted(issues)),
    )


HardwareSource = Callable[[], HardwareReading | None]


def observe_hardware_source(
    source: HardwareSource | None, *, rm_lease_count: int | None = None
) -> dict[str, object]:
    """Read an injected *pre-collected* sample (never probe OS in status).

    The source is expected to be an inexpensive in-process snapshot getter.
    Collection is separate and explicit; a slow or failing getter must not
    become an RM admission dependency. This function never returns raw IDs.
    """
    if source is None:
        return public_hardware_summary(None, rm_lease_count=rm_lease_count)
    try:
        sample = source()
    except Exception:
        result = public_hardware_summary(None, rm_lease_count=rm_lease_count)
        result["reason_codes"] = ["hardware_source_error"]
        return result
    return public_hardware_summary(sample, rm_lease_count=rm_lease_count)


def public_hardware_summary(
    sample: HardwareReading | None, *, rm_lease_count: int | None = None
) -> dict[str, object]:
    """Sanitized status: no UUIDs, PCI BDFs, boot IDs or false P1 fit."""
    if sample is None or not isinstance(sample, HardwareReading):
        return {
            "mode": "read_only",
            "result": "UNKNOWN",
            "reason_codes": ["missing_hardware_observation"],
            "authorizes_execution": False,
            "allocation_attribution": "unverified",
            "memory_domain_mapping": "unverified",
        }
    reasons = set(sample.issues)
    if sample.boot_id is None:
        reasons.add("boot_epoch_unavailable")
    if rm_lease_count is None:
        reasons.add("rm_lease_information_unavailable")
    elif type(rm_lease_count) is not int or rm_lease_count < 0:
        reasons.add("rm_lease_information_invalid")
    if any(d.vendor == "amd" for d in sample.devices):
        reasons.add("amd_memory_relation_unverified")
    if not sample.devices:
        reasons.add("no_gpu_observed")
    result = "PARTIAL" if reasons else "OBSERVED"
    return {
        "mode": "read_only",
        "result": result,
        "reason_codes": sorted(reasons),
        "counts": {
            "nvidia": sum(d.vendor == "nvidia" for d in sample.devices),
            "amd": sum(d.vendor == "amd" for d in sample.devices),
        },
        "memory_observations": {
            # These are *reported counters*, not a multi-GPU memory budget.
            "nvidia_dedicated": [
                {"total_bytes": d.total_bytes, "used_bytes": d.used_bytes}
                for d in sample.devices
                if d.vendor == "nvidia"
            ],
            "amd_driver_reported_unclassified": [
                {"total_bytes": d.total_bytes, "used_bytes": d.used_bytes}
                for d in sample.devices
                if d.vendor == "amd"
            ],
            "host_ram": (
                {"total_bytes": sample.host.total_bytes, "available_bytes": sample.host.available_bytes}
                if sample.host is not None
                else None
            ),
        },
        "rm_lease_count": rm_lease_count if type(rm_lease_count) is int and rm_lease_count >= 0 else None,
        "allocation_attribution": "unverified",
        "memory_domain_mapping": "unverified",
        "authorizes_execution": False,
    }
