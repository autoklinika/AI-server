from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Query, Request

from . import __version__
from .config import Settings, load_settings
from .models import (
    BatchAck,
    EventAck,
    EventIn,
    HealthResponse,
    HistoryResponse,
    RecommendationResponse,
    TelemetryBatch,
    utc_now,
)
from .storage import Storage


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    storage = Storage(resolved.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage.initialize()
        app.state.settings = resolved
        app.state.storage = storage
        yield

    app = FastAPI(
        title="AI Bridge",
        version=__version__,
        description=(
            "Telemetry and advisory AI bridge. "
            "This API intentionally exposes no ventilation control commands."
        ),
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        cfg: Settings = request.app.state.settings
        return HealthResponse(
            status="ok",
            service="ai-bridge",
            version=__version__,
            database=str(cfg.database_path),
            analysis_enabled=cfg.analysis_enabled,
            control_commands_supported=False,
        )

    @app.get("/api/v1/system/status", response_model=HealthResponse)
    def system_status(request: Request) -> HealthResponse:
        return health(request)

    @app.post("/api/v1/telemetry/batch", response_model=BatchAck)
    def ingest_batch(batch: TelemetryBatch, request: Request) -> BatchAck:
        duplicate, stored_samples = request.app.state.storage.store_batch(batch)
        return BatchAck(
            accepted=True,
            duplicate=duplicate,
            batch_id=batch.batch_id,
            received_at=utc_now(),
            stored_samples=stored_samples,
            message="duplicate already stored" if duplicate else "stored",
        )

    @app.post("/api/v1/events", response_model=EventAck)
    def ingest_event(event: EventIn, request: Request) -> EventAck:
        duplicate = request.app.state.storage.store_event(event)
        return EventAck(
            accepted=True,
            duplicate=duplicate,
            event_id=event.event_id,
            received_at=utc_now(),
        )

    @app.get("/api/v1/history", response_model=HistoryResponse)
    def history(
        request: Request,
        metric: str = Query(min_length=1, max_length=128),
        source: str | None = Query(default=None, max_length=64),
        device_id: str | None = Query(default=None, max_length=128),
        from_ts: datetime | None = Query(default=None, alias="from"),
        to_ts: datetime | None = Query(default=None, alias="to"),
        limit: int = Query(default=5000, ge=1, le=50000),
    ) -> HistoryResponse:
        points = request.app.state.storage.history(
            metric=metric,
            source=source,
            device_id=device_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
        return HistoryResponse(metric=metric, points=points)

    @app.get(
        "/api/v1/recommendations/latest",
        response_model=RecommendationResponse,
    )
    def latest_recommendation(
        request: Request,
        source: str = Query(default="ventilation_cm5", min_length=1, max_length=64),
    ) -> RecommendationResponse:
        recommendation = request.app.state.storage.latest_recommendation(source)
        return RecommendationResponse(
            available=recommendation is not None,
            recommendation=recommendation,
        )

    return app


app = create_app()
