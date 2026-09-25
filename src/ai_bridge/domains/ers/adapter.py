"""EcuRepairService case-domain API composition."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router
from .errors import ErsIntegrityConflict
from .storage.intake_repository import ErsIntakeRepository
from .storage.repository import (
    ErsCaseNotFound,
    ErsCaseRepository,
    ErsCaseVersionConflict,
    ErsInvalidCaseTransition,
)


class ERSAdapter:
    domain_id = "ecu-repair"

    def install(self, app: FastAPI, settings, database) -> None:
        app.state.ers_case_repository = ErsCaseRepository(database)
        app.state.ers_intake_repository = ErsIntakeRepository(database)
        app.include_router(router)

        @app.exception_handler(ErsCaseNotFound)
        async def case_not_found(_request: Request, _exc: ErsCaseNotFound):
            return JSONResponse(
                status_code=404,
                content={"status": "rejected", "error": "case_not_found"},
            )

        @app.exception_handler(ErsCaseVersionConflict)
        async def version_conflict(_request: Request, _exc: ErsCaseVersionConflict):
            return JSONResponse(
                status_code=409,
                content={"status": "rejected", "error": "case_version_conflict"},
            )

        @app.exception_handler(ErsInvalidCaseTransition)
        async def invalid_transition(_request: Request, _exc: ErsInvalidCaseTransition):
            return JSONResponse(
                status_code=409,
                content={"status": "rejected", "error": "invalid_case_transition"},
            )

        @app.exception_handler(ErsIntegrityConflict)
        async def integrity_conflict(_request: Request, _exc: ErsIntegrityConflict):
            return JSONResponse(
                status_code=409,
                content={"status": "rejected", "error": "ers_integrity_conflict"},
            )
