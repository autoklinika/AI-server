from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from ai_bridge import __version__
from ai_bridge.core.health import HealthComponents, HealthResponse
from ai_bridge.core.errors import BatchIdentityConflict, UnsupportedSchemaVersion
from ai_bridge.settings import Settings, get_settings
from ai_bridge.storage.database import Database

from ai_bridge.domains.contracts import DomainAdapter
from ai_bridge.domains.wvc.adapter import WVCAdapter


LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, domains: tuple[DomainAdapter, ...] | None = None) -> FastAPI:
    resolved = settings or get_settings()
    database = Database(resolved.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved
        app.state.database = database
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title="AI Bridge",
        version=__version__,
        description=(
            "Domain telemetry and advisory analysis. This API exposes no control commands."
        ),
        lifespan=lifespan,
    )

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

    for domain in (WVCAdapter(),) if domains is None else domains:
        domain.install(app, resolved, database)
    return app


app = create_app()
