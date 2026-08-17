from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_bridge.adapters.ventilation.schemas import VentilationTelemetryBatch
from ai_bridge.settings import Settings

from .database import Database
from .repository import IngestResult, VentilationTelemetryRepository


@dataclass(frozen=True)
class TelemetryStorageBackendStatus:
    backend: str
    location_label: str
    available: bool
    switch_supported: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "location_label": self.location_label,
            "available": self.available,
            "switch_supported": self.switch_supported,
        }


class VentilationTelemetryStorageBackend(Protocol):
    @property
    def backend_id(self) -> str: ...

    def ingest(self, batch: VentilationTelemetryBatch) -> IngestResult: ...

    def status(self) -> TelemetryStorageBackendStatus: ...


class SqlVentilationTelemetryStorageBackend:
    """Current RAW archive implementation backed by SQLAlchemy/Database.

    In production this is PostgreSQL on the AI Server. The API depends on this
    interface rather than the physical location, so a later NAS implementation
    can replace or mirror it without changing the CM5 telemetry contract.
    """

    backend_id = "sql"

    def __init__(self, database: Database, *, location_label: str) -> None:
        self._database = database
        self._repository = VentilationTelemetryRepository(database)
        self._location_label = location_label

    def ingest(self, batch: VentilationTelemetryBatch) -> IngestResult:
        return self._repository.ingest(batch)

    def status(self) -> TelemetryStorageBackendStatus:
        try:
            self._database.ping()
        except Exception:
            return TelemetryStorageBackendStatus(
                backend=self.backend_id,
                location_label=self._location_label,
                available=False,
            )
        return TelemetryStorageBackendStatus(
            backend=self.backend_id,
            location_label=self._location_label,
            available=True,
        )


def build_ventilation_storage_backend(
    settings: Settings,
    database: Database,
) -> VentilationTelemetryStorageBackend:
    # Settings currently accepts only "sql". Keep this explicit guard so adding
    # future options cannot accidentally fall through to the wrong backend.
    if settings.ventilation_storage_backend == "sql":
        return SqlVentilationTelemetryStorageBackend(
            database,
            location_label=settings.ventilation_storage_location_label,
        )
    raise ValueError(
        f"Unsupported ventilation storage backend: {settings.ventilation_storage_backend}"
    )
