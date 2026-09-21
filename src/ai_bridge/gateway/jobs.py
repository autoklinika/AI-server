"""Metadata-only D.2 lifecycle. No payload, output or exception storage."""
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from .priority import PRIORITY_CLASS_DEFAULTS, PriorityClass


class JobLifecycle(StrEnum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    ADMITTED = "admitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATES = frozenset({JobLifecycle.COMPLETED, JobLifecycle.FAILED,
                             JobLifecycle.CANCELLED, JobLifecycle.EXPIRED})
_TRANSITIONS = {
    JobLifecycle.SUBMITTED: {JobLifecycle.QUEUED, JobLifecycle.FAILED, JobLifecycle.CANCELLED},
    JobLifecycle.QUEUED: {JobLifecycle.ADMITTED, JobLifecycle.CANCELLED, JobLifecycle.EXPIRED},
    JobLifecycle.ADMITTED: {JobLifecycle.RUNNING, *TERMINAL_STATES},
    JobLifecycle.RUNNING: set(TERMINAL_STATES),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class JobMetadata:
    """Trusted adapter metadata, never constructed from an entire request body."""
    request_id: str = field(default_factory=lambda: f"req_{uuid4().hex}")
    domain: str = "shared"
    capability: str = "unknown"
    priority_class: PriorityClass | None = None


@dataclass(frozen=True, slots=True)
class JobState:
    job_id: str
    request_id: str
    domain: str
    capability: str
    priority_class: PriorityClass | None
    state: JobLifecycle = JobLifecycle.SUBMITTED
    assigned_provider: str | None = None
    assigned_node: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    queued_at: datetime | None = None
    admitted_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(cls, metadata: JobMetadata, priority: int) -> "JobState":
        semantic = metadata.priority_class
        if semantic is None:
            semantic = next((key for key, value in PRIORITY_CLASS_DEFAULTS.items()
                             if value == priority), None)
        return cls(f"job_{uuid4().hex}", metadata.request_id, metadata.domain,
                   metadata.capability, semantic)

    def transition(self, state: JobLifecycle) -> "JobState":
        if state not in _TRANSITIONS.get(self.state, set()):
            raise ValueError("invalid job lifecycle transition")
        # Wall-clock correction must not make lifecycle timestamps go backwards.
        now = max(utc_now(), self.created_at, self.queued_at or self.created_at,
                  self.admitted_at or self.created_at, self.started_at or self.created_at)
        stamp = {JobLifecycle.QUEUED: "queued_at", JobLifecycle.ADMITTED: "admitted_at",
                 JobLifecycle.RUNNING: "started_at"}.get(state, "finished_at")
        return replace(self, state=state, **{stamp: now})

    def snapshot(self) -> dict[str, object]:
        return {key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in asdict(self).items()}
