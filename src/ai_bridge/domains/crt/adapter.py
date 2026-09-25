from fastapi.responses import JSONResponse
from .api import router
from .service import SignalHypothesisService
from .storage.repository import CRTRepository, CRTError


class CRTAdapter:
    domain_id = "crt"

    def __init__(self, provider=None):
        self.provider = provider

    def install(self, app, settings, database):
        repository = CRTRepository(database)
        app.state.crt_repository = repository
        app.state.crt_analysis = SignalHypothesisService(repository, self.provider)
        app.include_router(router)

        @app.exception_handler(CRTError)
        async def crt_error(request, exc):
            return JSONResponse(status_code=exc.status, content={"status": "rejected", "error": exc.detail})
