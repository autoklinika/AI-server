"""Host-level resource sampling for benchmark runs.

The sampler is deliberately system-scoped. It does not claim per-model ownership
of shared UMA/VRAM while other platform services may be resident.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from pydantic import Field

from .contracts import StrictModel


class ResourcePoint(StrictModel):
    ram_used_bytes: int | None = Field(default=None, ge=0)
    vram_used_bytes: int | None = Field(default=None, ge=0)


class SystemResourceUsage(StrictModel):
    scope: str = "system"
    baseline: ResourcePoint
    peak: ResourcePoint
    final: ResourcePoint
    peak_delta_ram_bytes: int | None = Field(default=None, ge=0)
    peak_delta_vram_bytes: int | None = Field(default=None, ge=0)
    sample_count: int = Field(ge=1)
    interval_ms: float = Field(gt=0)


def _read_mem_used() -> int | None:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(rest.strip().split()[0]) * 1024
        if set(values) == {"MemTotal", "MemAvailable"}:
            return max(0, values["MemTotal"] - values["MemAvailable"])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _read_vram_used() -> int | None:
    values: list[int] = []
    for path in Path("/sys/class/drm").glob("card*/device/mem_info_vram_used"):
        try:
            values.append(int(path.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            continue
    return sum(values) if values else None


def read_system_resources() -> ResourcePoint:
    return ResourcePoint(
        ram_used_bytes=_read_mem_used(),
        vram_used_bytes=_read_vram_used(),
    )


class ResourceSampler:
    def __init__(
        self,
        *,
        interval_ms: float = 50.0,
        reader: Callable[[], ResourcePoint] = read_system_resources,
    ):
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        self.interval_ms = interval_ms
        self.reader = reader
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._points: list[ResourcePoint] = []

    def start(self) -> "ResourceSampler":
        if self._thread is not None:
            raise RuntimeError("resource sampler already started")
        self._points.append(self.reader())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        interval = self.interval_ms / 1000.0
        while not self._stop.wait(interval):
            self._points.append(self.reader())


    def stop(self) -> SystemResourceUsage:
        if self._thread is None:
            raise RuntimeError("resource sampler not started")
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_ms / 1000.0 * 4))
        self._points.append(self.reader())
        baseline = self._points[0]
        final = self._points[-1]
        ram_values = [
            point.ram_used_bytes
            for point in self._points
            if point.ram_used_bytes is not None
        ]
        vram_values = [
            point.vram_used_bytes
            for point in self._points
            if point.vram_used_bytes is not None
        ]
        peak = ResourcePoint(
            ram_used_bytes=max(ram_values) if ram_values else None,
            vram_used_bytes=max(vram_values) if vram_values else None,
        )

        def delta(peak_value: int | None, base_value: int | None) -> int | None:
            if peak_value is None or base_value is None:
                return None
            return max(0, peak_value - base_value)


        return SystemResourceUsage(
            baseline=baseline,
            peak=peak,
            final=final,
            peak_delta_ram_bytes=delta(
                peak.ram_used_bytes, baseline.ram_used_bytes
            ),
            peak_delta_vram_bytes=delta(
                peak.vram_used_bytes, baseline.vram_used_bytes
            ),
            sample_count=len(self._points),
            interval_ms=self.interval_ms,
        )
