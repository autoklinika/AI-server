"""Bounded metadata-only observability for Platform API v1.

No prompts, response bodies, auth data, raw URLs, user identifiers or exception
text are stored. The snapshot intentionally derives job timing from the existing
bounded Resource Manager history rather than creating a second job database.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import resource
from threading import Lock
from time import monotonic


_ALLOWED_ERRORS = frozenset({
    "invalid_request", "unauthorized", "forbidden", "not_found", "queue_full",
    "deadline_exceeded", "provider_unavailable", "capability_unavailable",
    "internal_error", "client_error", "server_error",
})

_TRACE_LIMIT = 256
_TRACE_IGNORED_ROUTES = frozenset({
    "/health", "/observability", "/operations", "/jobs", "/models", "/systems",
    "/apps", "/benchmarks", "/traces", "/traces/{request_id}", "/system-map",
    "/incidents", "/incidents/{incident_id}",
})


def _trace_kind(route: str) -> str:
    if route == "/ai":
        return "ai"
    if route == "/knowledge/ask":
        return "knowledge-rag"
    if route == "/knowledge/search":
        return "knowledge-search"
    if route.startswith("/knowledge/documents/"):
        return "knowledge-document"
    if route.startswith("/benchmarks/"):
        return "benchmark"
    if route.startswith("/jobs/"):
        return "job"
    return "platform"


def _record_trace(route: str) -> bool:
    return route not in _TRACE_IGNORED_ROUTES and route != "unmatched"


def _milliseconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
    except (TypeError, ValueError):
        return None


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "avg_ms": None, "max_ms": None}
    return {"count": len(values), "avg_ms": round(sum(values) / len(values), 3),
            "max_ms": round(max(values), 3)}


def _rss_bytes() -> int | None:
    try:
        pages = int(open("/proc/self/statm", encoding="ascii").read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


@dataclass(slots=True)
class PlatformRequestMetrics:
    """Low-cardinality counters plus bounded metadata-only request traces."""

    started_monotonic: float = field(default_factory=monotonic)
    total: int = 0
    in_flight: int = 0
    duration_ms_total: float = 0.0
    duration_ms_max: float = 0.0
    status_classes: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)
    recent: deque = field(default_factory=lambda: deque(maxlen=_TRACE_LIMIT))
    _lock: Lock = field(default_factory=Lock, repr=False)

    def begin(self) -> float:
        with self._lock:
            self.total += 1
            self.in_flight += 1
        return monotonic()

    def finish(
        self,
        started: float,
        status: int,
        error_code: str | None = None,
        *,
        request_id: str | None = None,
        method: str | None = None,
        route: str | None = None,
    ) -> float:
        elapsed = max(0.0, (monotonic() - started) * 1000)
        category = f"{max(1, min(5, status // 100))}xx"
        with self._lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.duration_ms_total += elapsed
            self.duration_ms_max = max(self.duration_ms_max, elapsed)
            self.status_classes[category] += 1
            if error_code:
                self.errors[error_code if error_code in _ALLOWED_ERRORS else "internal_error"] += 1
            if request_id and method and route and _record_trace(route):
                self.recent.append({
                    "trace_id": request_id,
                    "request_id": request_id,
                    "kind": _trace_kind(route),
                    "method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed, 3),
                    "error_class": error_code,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
        return elapsed

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            completed = sum(self.status_classes.values())
            return {
                "total": self.total,
                "completed": completed,
                "in_flight": self.in_flight,
                "status_classes": dict(sorted(self.status_classes.items())),
                "errors": dict(sorted(self.errors.items())),
                "duration": {
                    "count": completed,
                    "avg_ms": round(self.duration_ms_total / completed, 3) if completed else None,
                    "max_ms": round(self.duration_ms_max, 3) if completed else None,
                },
                "uptime_seconds": round(monotonic() - self.started_monotonic, 3),
            }

    def traces(self, limit: int = 100) -> list[dict[str, object]]:
        bounded = max(1, min(_TRACE_LIMIT, limit))
        with self._lock:
            return [dict(item) for item in list(self.recent)[-bounded:]][::-1]

    def trace(self, request_id: str) -> dict[str, object] | None:
        with self._lock:
            for item in reversed(self.recent):
                if item["request_id"] == request_id:
                    return dict(item)
        return None

def runtime_resources() -> dict[str, object]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"rss_bytes": _rss_bytes(),
            "cpu_user_seconds": round(usage.ru_utime, 3),
            "cpu_system_seconds": round(usage.ru_stime, 3)}


def job_metrics(snapshot: dict[str, object]) -> dict[str, object]:
    jobs = list(snapshot.get("recent_jobs", []))
    jobs += [item["job"] for item in snapshot.get("active", [])]
    jobs += [item["job"] for item in snapshot.get("queued", [])]
    states = Counter(str(job.get("state")) for job in jobs)
    capabilities = Counter(str(job.get("capability")) for job in jobs)
    providers = Counter(str(job.get("assigned_provider")) for job in jobs if job.get("assigned_provider"))
    nodes = Counter(str(job.get("assigned_node")) for job in jobs if job.get("assigned_node"))
    queue_waits = [value for job in jobs
                   if (value := _milliseconds(job.get("queued_at"), job.get("admitted_at"))) is not None]
    execution = [value for job in jobs
                 if (value := _milliseconds(job.get("started_at"), job.get("finished_at"))) is not None]
    failures = {
        "execution_failed": states.get("failed", 0),
        "cancelled": states.get("cancelled", 0),
        "deadline_exceeded": states.get("expired", 0),
    }
    return {
        "observed": len(jobs), "states": dict(sorted(states.items())),
        "capabilities": dict(sorted(capabilities.items())),
        "providers": dict(sorted(providers.items())), "nodes": dict(sorted(nodes.items())),
        "queue_wait": _summary(queue_waits), "execution": _summary(execution),
        "terminal_failures": failures,
    }
