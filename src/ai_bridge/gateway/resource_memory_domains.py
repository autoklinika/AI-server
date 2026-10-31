"""P2-A3 AMD memory apertures: observations, NOT a shared-RAM budget.

VRAM, visible VRAM and GTT are overlapping / driver-defined address spaces.
No additive capacity, host reservation, P1 topology or GPU ownership is ever
derived from these counters. Real memory mapping needs firmware evidence.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .resource_hardware import HardwareReading

_CARD = re.compile(r"card[0-9]+")
_PCI = re.compile(r"(?i)[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")
_FIELDS = (
    "mem_info_vram_total",
    "mem_info_vis_vram_total",
    "mem_info_gtt_total",
    "mem_info_gtt_used",
)


@dataclass(frozen=True, slots=True)
class AmdAperture:
    pci_bdf: str
    vram_bytes: int | None
    visible_vram_bytes: int | None
    gtt_bytes: int | None
    gtt_used_bytes: int | None


@dataclass(frozen=True, slots=True)
class AmdApertureSnapshot:
    observed_at_ns: int
    boot_id: str | None
    apertures: tuple[AmdAperture, ...]
    issues: tuple[str, ...]
    authorizes_execution: Literal[False] = False


def _counter(path: Path) -> int | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(80)
    except OSError:
        return None
    if len(raw) > 64:
        return None
    value = raw.strip()
    if not value.isascii() or not value.isdecimal():
        return None
    return int(value)


def collect_amd_apertures(
    hardware: HardwareReading,
    *,
    drm_root: Path = Path("/sys/class/drm"),
    now_ns: Callable[[], int] = time.monotonic_ns,
) -> AmdApertureSnapshot:
    """Explicit sysfs-only collection; no processes, locks, driver calls."""
    if not isinstance(hardware, HardwareReading):
        raise TypeError("hardware observation required")
    known = {
        item.pci_bdf for item in hardware.devices if item.vendor == "amd"
    }
    issues: set[str] = set()
    rows: list[AmdAperture] = []
    seen: set[str] = set()
    try:
        cards = sorted(drm_root.iterdir(), key=lambda card: card.name)
    except OSError:
        cards = []
        issues.add("amd_drm_unavailable")
    for card in cards:
        if not _CARD.fullmatch(card.name):
            continue
        device = card / "device"
        try:
            vendor = (device / "vendor").read_text().strip().lower()
        except (OSError, UnicodeError):
            continue
        if vendor != "0x1002":
            continue
        try:
            bdf = device.resolve(strict=True).name.lower()
        except (OSError, ValueError):
            issues.add("amd_identity_unavailable")
            continue
        if not _PCI.fullmatch(bdf) or bdf not in known:
            issues.add("amd_unexpected_identity")
            continue
        if bdf in seen:
            issues.add("amd_duplicate_pci")
            continue
        seen.add(bdf)
        counters = {name: _counter(device / name) for name in _FIELDS}
        vram = counters["mem_info_vram_total"]
        visible = counters["mem_info_vis_vram_total"]
        gtt = counters["mem_info_gtt_total"]
        gtt_used = counters["mem_info_gtt_used"]
        if (vram is None or vram <= 0 or visible is None
                or visible > vram or gtt is None or gtt <= 0
                or gtt_used is None or gtt_used > gtt):
            issues.add("amd_aperture_counters_incomplete")
        rows.append(
            AmdAperture(
                pci_bdf=bdf,
                vram_bytes=vram,
                visible_vram_bytes=visible,
                gtt_bytes=gtt,
                gtt_used_bytes=gtt_used,
            )
        )
    if seen != known:
        issues.add("amd_aperture_inventory_incomplete")
    return AmdApertureSnapshot(
        observed_at_ns=now_ns(),
        boot_id=hardware.boot_id,
        apertures=tuple(sorted(rows, key=lambda item: item.pci_bdf)),
        issues=tuple(sorted(issues)),
    )


def summarize_memory_relation(
    hardware: HardwareReading | None,
    snapshot: AmdApertureSnapshot | None,
    *,
    now_ns: int,
) -> dict[str, object]:
    """Describe non-additive counters and *always* refuse inferred UMA budget."""
    reasons: set[str] = {"firmware_memory_mapping_not_attested"}
    base: dict[str, object] = {
        "mode": "read_only",
        "memory_domain_mapping": "unverified",
        "authorizes_execution": False,
        "reason_codes": [],
        "amd_apertures": [],
        "host_ram_visible_bytes": None,
    }
    if not isinstance(hardware, HardwareReading) or not isinstance(
        snapshot, AmdApertureSnapshot
    ):
        reasons.add("missing_memory_evidence")
        base["reason_codes"] = sorted(reasons)
        return base
    if (type(now_ns) is not int or now_ns < 0 or hardware.boot_id is None
            or snapshot.boot_id != hardware.boot_id):
        reasons.add("memory_epoch_mismatch")
    elif (snapshot.observed_at_ns < 0 or snapshot.observed_at_ns > now_ns
          or hardware.observed_at_ns > now_ns
          or now_ns - snapshot.observed_at_ns > 5_000_000_000
          or now_ns - hardware.observed_at_ns > 5_000_000_000):
        reasons.add("memory_sample_not_fresh")
    if snapshot.issues:
        reasons.add("incomplete_amd_memory_evidence")
    if hardware.host is None:
        reasons.add("host_ram_unavailable")
    else:
        base["host_ram_visible_bytes"] = hardware.host.total_bytes
    known = {d.pci_bdf: d for d in hardware.devices if d.vendor == "amd"}
    if len(snapshot.apertures) != len(known):
        reasons.add("amd_gpu_apertures_unmatched")
    apertures: list[dict[str, int | None]] = []
    seen: set[str] = set()
    for aperture in snapshot.apertures:
        if not isinstance(aperture, AmdAperture) or aperture.pci_bdf not in known:
            reasons.add("amd_gpu_apertures_unmatched")
            continue
        if aperture.pci_bdf in seen:
            reasons.add("amd_gpu_apertures_unmatched")
            continue
        seen.add(aperture.pci_bdf)
        driver = known[aperture.pci_bdf]
        if driver.total_bytes != aperture.vram_bytes:
            reasons.add("inconsistent_amd_vram_counters")
        if hardware.host is not None and aperture.vram_bytes is not None:
            if aperture.vram_bytes > hardware.host.total_bytes:
                reasons.add("amd_vram_exceeds_cpu_visible_ram")
        apertures.append({
            "driver_vram_bytes": aperture.vram_bytes,
            "visible_vram_bytes": aperture.visible_vram_bytes,
            "gtt_aperture_bytes": aperture.gtt_bytes,
            "gtt_used_bytes": aperture.gtt_used_bytes,
        })
    if seen != set(known):
        reasons.add("amd_gpu_apertures_unmatched")
    base["amd_apertures"] = apertures
    base["reason_codes"] = sorted(reasons)
    return base
