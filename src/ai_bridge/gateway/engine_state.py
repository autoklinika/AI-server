"""Pure diagnostics over trusted Gateway snapshots; never execution authority."""
from dataclasses import asdict, dataclass
from enum import StrEnum
import re


class ResourceState(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SWITCHING = "SWITCHING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    id: str
    provider_id: str
    status: str
    execution_available: bool

    def __post_init__(self):
        for value in (self.id, self.provider_id):
            if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
                raise ValueError("invalid engine/provider id")
        if not isinstance(self.status, str) or self.status not in {
            "configured", "not_installed", "unavailable"
        }:
            raise ValueError("invalid engine status")
        if type(self.execution_available) is not bool:
            raise ValueError("execution_available must be boolean")
        if self.execution_available and self.status != "configured":
            raise ValueError("unavailable engine cannot offer execution")


@dataclass(frozen=True, slots=True)
class EngineRegistry:
    engines: tuple[EngineDescriptor, ...]

    def __post_init__(self):
        engines = tuple(self.engines)
        if not engines or any(type(engine) is not EngineDescriptor for engine in engines):
            raise ValueError("engine descriptors required")
        for field in ("id", "provider_id"):
            if len({getattr(engine, field) for engine in engines}) != len(engines):
                raise ValueError(f"duplicate engine {field}")
        object.__setattr__(self, "engines", engines)

    def snapshot(self):
        return [asdict(engine) for engine in self.engines]


DEFAULT_ENGINES = EngineRegistry((
    EngineDescriptor("ollama", "ollama-local", "configured", True),
    EngineDescriptor("comfyui", "comfyui-local", "configured", True),
    EngineDescriptor("vision", "vision-local", "not_installed", False),
))


def resource_manager_snapshot(scheduler, residency, registry=DEFAULT_ENGINES):
    """Derive occupancy, not physical GPU use/readiness, without I/O or mutation.

    Call only with server-owned snapshots. Waiting jobs do not own the resource;
    multiple active tickets are inconsistent with this exclusive resource view.
    Configured execution availability describes an adapter, never a GPU grant.
    """
    result = {
        "schema_version": 1,
        "state": ResourceState.BLOCKED.value,
        "active_engine": None,
        "target_engine": None,
        "reason": "incomplete_or_invalid_snapshot",
        "engines": registry.snapshot(),
    }

    def view(state, reason, owner=None, target=None):
        result.update(state=state.value, reason=reason,
                      active_engine=owner, target_engine=target)
        return result

    if not isinstance(scheduler, dict) or not isinstance(residency, dict):
        return result
    count = scheduler.get("active_count")
    active = scheduler.get("active")
    queued = scheduler.get("queued_count")
    if (type(count) is not int or count < 0
            or not isinstance(active, list) or len(active) != count
            or type(queued) is not int or queued < 0
            or type(scheduler.get("admission_blocked")) is not bool
            or type(residency.get("recovery_required")) is not bool):
        return result
    if count > 1:
        return view(ResourceState.BLOCKED, "multiple_active_tickets")
    if scheduler["admission_blocked"] or residency["recovery_required"]:
        return view(ResourceState.BLOCKED, "recovery_or_admission_blocked")
    legacy = residency.get("state")
    if not isinstance(legacy, str) or legacy not in {
        "llm", "media", "draining_ollama", "freeing_comfy"
    }:
        return view(ResourceState.BLOCKED, "unknown_or_blocked_residency")
    providers = {engine.provider_id: engine for engine in registry.engines}
    engines = {engine.id: engine for engine in registry.engines}
    owners = set()
    if count:
        job = active[0].get("job") if isinstance(active[0], dict) else None
        if not isinstance(job, dict) or job.get("state") not in ("admitted", "running"):
            return result
        workload = job.get("workload")
        if not isinstance(workload, list) or not workload:
            return result
        for binding in workload:
            if not isinstance(binding, dict) or any(
                not isinstance(binding.get(key), str) or not binding[key]
                for key in ("provider", "node", "capability")
            ):
                return result
            engine = providers.get(binding["provider"])
            if engine is None or not engine.execution_available:
                return view(ResourceState.BLOCKED, "unknown_or_unavailable_engine")
            owners.add(engine.id)
    if legacy == "llm":
        if not count:
            return view(ResourceState.IDLE, "no_active_ticket")
        if "ollama" not in owners:
            return view(ResourceState.BLOCKED, "inconsistent_workload")
        return view(ResourceState.RUNNING, "active_ticket",
                    "ollama" if owners == {"ollama"} else None)
    if not count or "comfyui" not in owners:
        return view(ResourceState.BLOCKED, "media_without_active_workload")
    if legacy == "media":
        return view(ResourceState.RUNNING, "active_media_lease", "comfyui")
    if any(name not in engines or not engines[name].execution_available
           for name in ("ollama", "comfyui")):
        return view(ResourceState.BLOCKED, "transition_engine_unavailable")
    owner, target = (("ollama", "comfyui") if legacy == "draining_ollama"
                     else ("comfyui", "ollama"))
    return view(ResourceState.SWITCHING, "legacy_transition", owner, target)
