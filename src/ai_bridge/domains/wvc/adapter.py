"""WVC telemetry and read-only advisory API composition."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .api import router
from .storage.repository import VentilationTelemetryRepository
from .storage.analysis_repository import VentilationAnalysisRepository


class WVCAdapter:
    domain_id = "wvc"

    def install(self, app: FastAPI, settings, database) -> None:
        # State names and routes remain compatibility contracts during migration.
        app.state.ventilation_repository = VentilationTelemetryRepository(database)
        app.state.ventilation_analysis_repository = VentilationAnalysisRepository(database)
        app.include_router(router)

        @app.middleware("http")
        async def reject_oversized_telemetry(request: Request, call_next):
            if request.method == "POST" and request.url.path == "/api/v1/ventilation/telemetry/batches":
                length = request.headers.get("content-length")
                if length is not None:
                    try:
                        if int(length) > settings.telemetry_max_body_bytes:
                            return JSONResponse(status_code=413, content={"status": "rejected", "error": "request_too_large"})
                    except ValueError:
                        return JSONResponse(status_code=400, content={"status": "rejected", "error": "invalid_content_length"})
            return await call_next(request)
