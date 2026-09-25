from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update

from ai_bridge.storage.database import Database

from .models import (
    ErsCaseCounterModel,
    ErsCaseEventModel,
    ErsCaseModel,
)


CASE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"open", "cancelled"},
    "open": {"resolved", "cancelled"},
    "resolved": {"open", "closed"},
    "closed": {"open"},
    "cancelled": set(),
}

WORK_STATES = {
    "intake",
    "diagnosing",
    "awaiting_measurement",
    "awaiting_parts",
    "repairing",
    "verifying",
    "none",
}


class ErsCaseNotFound(KeyError):
    pass


class ErsCaseVersionConflict(RuntimeError):
    pass


class ErsInvalidCaseTransition(ValueError):
    pass


@dataclass(frozen=True)
class ErsCaseSnapshot:
    id: UUID
    case_code: str
    legacy_case_code: str | None
    title: str
    status: str
    work_state: str | None
    row_version: int
    opened_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: str
    metadata: dict


@dataclass(frozen=True)
class ErsCaseEventSnapshot:
    id: UUID
    case_id: UUID
    event_seq: int
    event_type: str
    previous_status: str | None
    new_status: str | None
    previous_work_state: str | None
    new_work_state: str | None
    actor_id: str
    request_id: str | None
    correlation_id: str | None
    occurred_at: datetime
    payload: dict


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ErsCaseRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_case(
        self,
        *,
        title: str,
        actor_id: str,
        legacy_case_code: str | None = None,
        metadata: dict | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsCaseSnapshot:
        title = title.strip()
        actor_id = actor_id.strip()
        if not title:
            raise ValueError("title is required")
        if not actor_id:
            raise ValueError("actor_id is required")

        now = _now()
        with self._database.session() as session:
            number = self._allocate_case_number(session)
            case = ErsCaseModel(
                id=uuid4(),
                case_code=f"CASE-{number:06d}",
                legacy_case_code=legacy_case_code,
                title=title,
                status="draft",
                work_state="intake",
                row_version=1,
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
                metadata_json={} if metadata is None else dict(metadata),
            )
            session.add(case)
            session.flush()
            session.add(
                self._event(
                    case=case,
                    event_type="created",
                    actor_id=actor_id,
                    previous_status=None,
                    new_status="draft",
                    previous_work_state=None,
                    new_work_state="intake",
                    request_id=request_id,
                    correlation_id=correlation_id,
                    payload={},
                    occurred_at=now,
                )
            )
            return self._case_snapshot(case)

    def get_case(self, case_id: UUID) -> ErsCaseSnapshot:
        with self._database.session() as session:
            case = session.get(ErsCaseModel, case_id)
            if case is None:
                raise ErsCaseNotFound(str(case_id))
            return self._case_snapshot(case)

    def get_case_by_legacy_code(self, legacy_case_code: str) -> ErsCaseSnapshot | None:
        code = legacy_case_code.strip()
        if not code:
            raise ValueError("legacy_case_code is required")
        with self._database.session() as session:
            row = session.scalar(
                select(ErsCaseModel).where(ErsCaseModel.legacy_case_code == code)
            )
            return None if row is None else self._case_snapshot(row)

    def list_events(self, case_id: UUID) -> tuple[ErsCaseEventSnapshot, ...]:
        with self._database.session() as session:
            exists = session.get(ErsCaseModel, case_id)
            if exists is None:
                raise ErsCaseNotFound(str(case_id))
            rows = session.scalars(
                select(ErsCaseEventModel)
                .where(ErsCaseEventModel.case_id == case_id)
                .order_by(ErsCaseEventModel.event_seq)
            ).all()
            return tuple(self._event_snapshot(row) for row in rows)

    def update_case(
        self,
        case_id: UUID,
        *,
        expected_row_version: int,
        actor_id: str,
        title: str | None = None,
        work_state: str | None = None,
        metadata: dict | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ErsCaseSnapshot:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("actor_id is required")
        if expected_row_version < 1:
            raise ValueError("expected_row_version must be >= 1")
        if work_state is not None and work_state not in WORK_STATES:
            raise ValueError("invalid work_state")
        if title is not None and not title.strip():
            raise ValueError("title must be non-empty")

        with self._database.session() as session:
            current = session.get(ErsCaseModel, case_id)
            if current is None:
                raise ErsCaseNotFound(str(case_id))
            if current.row_version != expected_row_version:
                raise ErsCaseVersionConflict(str(case_id))

            previous_work_state = current.work_state
            values: dict = {
                "row_version": expected_row_version + 1,
                "updated_at": _now(),
                "updated_by": actor_id,
            }
            if title is not None:
                values["title"] = title.strip()
            if work_state is not None:
                values["work_state"] = work_state
            if metadata is not None:
                values["metadata_json"] = dict(metadata)

            updated = self._atomic_update(
                session, case_id, expected_row_version, values
            )
            session.add(
                self._event(
                    case=updated,
                    event_type="updated",
                    actor_id=actor_id,
                    previous_status=current.status,
                    new_status=updated.status,
                    previous_work_state=previous_work_state,
                    new_work_state=updated.work_state,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    payload={
                        "title_changed": title is not None,
                        "metadata_changed": metadata is not None,
                    },
                    occurred_at=updated.updated_at,
                )
            )
            return self._case_snapshot(updated)

    def transition_status(
        self,
        case_id: UUID,
        *,
        to_status: str,
        expected_row_version: int,
        actor_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
        payload: dict | None = None,
    ) -> ErsCaseSnapshot:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("actor_id is required")
        if expected_row_version < 1:
            raise ValueError("expected_row_version must be >= 1")

        with self._database.session() as session:
            current = session.get(ErsCaseModel, case_id)
            if current is None:
                raise ErsCaseNotFound(str(case_id))
            if current.row_version != expected_row_version:
                raise ErsCaseVersionConflict(str(case_id))
            if to_status not in CASE_TRANSITIONS.get(current.status, set()):
                raise ErsInvalidCaseTransition(
                    f"{current.status} -> {to_status} is not allowed"
                )

            now = _now()
            previous_status = current.status
            previous_work_state = current.work_state
            values: dict = {
                "status": to_status,
                "row_version": expected_row_version + 1,
                "updated_at": now,
                "updated_by": actor_id,
            }
            if to_status == "open":
                values["opened_at"] = current.opened_at or now
                if current.status in {"resolved", "closed"}:
                    values["resolved_at"] = None
                    values["closed_at"] = None
            elif to_status == "resolved":
                values["resolved_at"] = now
            elif to_status == "closed":
                values["closed_at"] = now

            updated = self._atomic_update(
                session, case_id, expected_row_version, values
            )
            event_type = (
                "reopened"
                if previous_status == "closed" and to_status == "open"
                else "status_changed"
            )
            session.add(
                self._event(
                    case=updated,
                    event_type=event_type,
                    actor_id=actor_id,
                    previous_status=previous_status,
                    new_status=to_status,
                    previous_work_state=previous_work_state,
                    new_work_state=updated.work_state,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    payload={} if payload is None else dict(payload),
                    occurred_at=now,
                )
            )
            return self._case_snapshot(updated)

    @staticmethod
    def _allocate_case_number(session) -> int:
        statement = (
            update(ErsCaseCounterModel)
            .where(ErsCaseCounterModel.counter_name == "case")
            .values(next_value=ErsCaseCounterModel.next_value + 1)
            .returning(ErsCaseCounterModel.next_value)
        )
        value = session.execute(statement).scalar_one_or_none()
        if value is None:
            raise RuntimeError("ERS case counter is not initialized")
        return int(value) - 1

    @staticmethod
    def _atomic_update(session, case_id: UUID, expected: int, values: dict) -> ErsCaseModel:
        statement = (
            update(ErsCaseModel)
            .where(
                ErsCaseModel.id == case_id,
                ErsCaseModel.row_version == expected,
            )
            .values(**values)
            .returning(ErsCaseModel)
        )
        updated = session.scalars(statement).one_or_none()
        if updated is None:
            raise ErsCaseVersionConflict(str(case_id))
        return updated

    @staticmethod
    def _event(
        *,
        case: ErsCaseModel,
        event_type: str,
        actor_id: str,
        previous_status: str | None,
        new_status: str | None,
        previous_work_state: str | None,
        new_work_state: str | None,
        request_id: str | None,
        correlation_id: str | None,
        payload: dict,
        occurred_at: datetime,
    ) -> ErsCaseEventModel:
        return ErsCaseEventModel(
            id=uuid4(),
            case_id=case.id,
            event_seq=case.row_version,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            previous_work_state=previous_work_state,
            new_work_state=new_work_state,
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    @staticmethod
    def _case_snapshot(row: ErsCaseModel) -> ErsCaseSnapshot:
        return ErsCaseSnapshot(
            id=row.id,
            case_code=row.case_code,
            legacy_case_code=row.legacy_case_code,
            title=row.title,
            status=row.status,
            work_state=row.work_state,
            row_version=row.row_version,
            opened_at=row.opened_at,
            resolved_at=row.resolved_at,
            closed_at=row.closed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            updated_by=row.updated_by,
            metadata=dict(row.metadata_json),
        )

    @staticmethod
    def _event_snapshot(row: ErsCaseEventModel) -> ErsCaseEventSnapshot:
        return ErsCaseEventSnapshot(
            id=row.id,
            case_id=row.case_id,
            event_seq=row.event_seq,
            event_type=row.event_type,
            previous_status=row.previous_status,
            new_status=row.new_status,
            previous_work_state=row.previous_work_state,
            new_work_state=row.new_work_state,
            actor_id=row.actor_id,
            request_id=row.request_id,
            correlation_id=row.correlation_id,
            occurred_at=row.occurred_at,
            payload=dict(row.payload),
        )
