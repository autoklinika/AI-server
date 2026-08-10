from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from ai_bridge import __version__
from ai_bridge.adapters.ventilation.schemas import HealthComponents, HealthResponse
from ai_bridge.core.errors import BatchIdentityConflict, UnsupportedSchemaVersion
from ai_bridge.settings import Settings, get_settings
from ai_bridge.storage.database import Database
from ai_bridge.storage.repository import VentilationTelemetryRepository

from .ventilation import router as ventilation_router


LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    database = Database(resolved.database_url)
    repository = VentilationTelemetryRepository(database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved
        app.state.database = database
        app.state.ventilation_repository = repository
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title="AI Bridge",
        version=__version__,
        description=(
            "Local analytical bridge. CM5 remains the autonomous ventilation "
            "controller; this API exposes no control commands."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def reject_oversized_telemetry(request: Request, call_next):
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/ventilation/telemetry/batches"
        ):
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    if int(length) > resolved.telemetry_max_body_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "status": "rejected",
                                "error": "request_too_large",
                            },
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"status": "rejected", "error": "invalid_content_length"},
                    )
        return await call_next(request)

    @app.exception_handler(UnsupportedSchemaVersion)
    async def unsupported_schema_handler(_request: Request, exc: UnsupportedSchemaVersion):
        return JSONResponse(
            status_code=400,
            content={
                "status": "rejected",
                "error": "unsupported_schema_version",
                "supported_versions": list(exc.supported),
            },
        )

    @app.exception_handler(BatchIdentityConflict)
    async def batch_conflict_handler(_request: Request, exc: BatchIdentityConflict):
        return JSONResponse(
            status_code=409,
            content={"status": "rejected", "error": "batch_identity_conflict", "detail": str(exc)},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_request: Request, exc: SQLAlchemyError):
        LOGGER.exception("Database operation failed", exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"status": "rejected", "error": "storage_unavailable"},
        )

    @app.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        try:
            request.app.state.database.ping()
            return HealthResponse(
                status="ok",
                version=__version__,
                components=HealthComponents(database="ok"),
            )
        except SQLAlchemyError:
            return HealthResponse(
                status="unavailable",
                version=__version__,
                components=HealthComponents(database="unavailable"),
            )

    app.include_router(ventilation_router)
    return app


app = create_app()
