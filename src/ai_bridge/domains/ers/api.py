from __future__ import annotations

from dataclasses import asdict
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError

from .errors import ErsIntegrityConflict
from .schemas import (
    AssetCreateRequest,
    CaseCreateRequest,
    CasePatchRequest,
    CaseTransitionRequest,
    DiagnosticStepCreateRequest,
    DtcCreateRequest,
    EcuCreateRequest,
    MeasurementCreateRequest,
    SymptomCreateRequest,
)
from .storage.repository import ErsInvalidCaseTransition


router = APIRouter(prefix="/api/v1/ecu-repair", tags=["ecu-repair"])
_ETAG = re.compile(r'^(?:W/)?"([1-9][0-9]*)"$')


def _expected_version(request: Request) -> int:
    raw = request.headers.get("if-match")
    if raw is None:
        raise HTTPException(status_code=428, detail="if_match_required")
    match = _ETAG.fullmatch(raw.strip())
    if match is None:
        raise HTTPException(status_code=400, detail="invalid_if_match")
    return int(match.group(1))


def _request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id")


def _correlation_id(request: Request) -> str | None:
    return request.headers.get("x-correlation-id")


def _set_etag(response: Response, row_version: int) -> None:
    response.headers["ETag"] = f'W/"{row_version}"'


def _case_payload(case) -> dict:
    return asdict(case)


def _mutation_payload(result) -> dict:
    return {
        "schema_version": 1,
        "case": _case_payload(result.case),
        "entity_id": result.entity_id,
        "extra_ids": dict(result.extra_ids),
    }


@router.post("/cases", status_code=201)
def create_case(
    body: CaseCreateRequest,
    request: Request,
    response: Response,
):
    repository = request.app.state.ers_case_repository
    try:
        case = repository.create_case(
            title=body.title,
            actor_id=body.actor_id,
            legacy_case_code=body.legacy_case_code,
            metadata=body.metadata,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, case.row_version)
    return {"schema_version": 1, "case": _case_payload(case)}


@router.get("/cases")
def list_cases(request: Request):
    cases = request.app.state.ers_case_repository.list_cases(limit=100)
    return {
        "schema_version": 1,
        "cases": [_case_payload(case) for case in cases],
        "count": len(cases),
        "limit": 100,
    }


@router.get("/cases/{case_id}")
def get_case(case_id: UUID, request: Request, response: Response):
    detail = request.app.state.ers_intake_repository.get_case_detail(case_id)
    events = request.app.state.ers_case_repository.list_events(case_id)
    case = detail["case"]
    _set_etag(response, case.row_version)
    return {
        "schema_version": 1,
        **{key: value for key, value in detail.items() if key != "case"},
        "case": _case_payload(case),
        "events": [asdict(event) for event in events],
    }


@router.patch("/cases/{case_id}")
def update_case(
    case_id: UUID,
    body: CasePatchRequest,
    request: Request,
    response: Response,
):
    try:
        case = request.app.state.ers_case_repository.update_case(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            title=body.title,
            work_state=body.work_state,
            metadata=body.metadata,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, case.row_version)
    return {"schema_version": 1, "case": _case_payload(case)}


@router.post("/cases/{case_id}/events")
def transition_case(
    case_id: UUID,
    body: CaseTransitionRequest,
    request: Request,
    response: Response,
):
    try:
        case = request.app.state.ers_case_repository.transition_status(
            case_id,
            to_status=body.to_status,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
            payload=body.payload,
        )
    except ErsInvalidCaseTransition:
        raise
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, case.row_version)
    return {"schema_version": 1, "case": _case_payload(case)}


@router.post("/cases/{case_id}/assets", status_code=201)
def add_asset(
    case_id: UUID,
    body: AssetCreateRequest,
    request: Request,
    response: Response,
):
    try:
        result = request.app.state.ers_intake_repository.add_asset(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            asset_kind=body.asset_kind,
            role=body.role,
            manufacturer=body.manufacturer,
            model=body.model,
            vin=body.vin,
            serial_number=body.serial_number,
            production_date=body.production_date,
            engine_identity=body.engine_identity,
            provenance_id=body.provenance_id,
            metadata=body.metadata,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, result.case.row_version)
    return _mutation_payload(result)


@router.post("/cases/{case_id}/ecus", status_code=201)
def add_ecu(
    case_id: UUID,
    body: EcuCreateRequest,
    request: Request,
    response: Response,
):
    try:
        result = request.app.state.ers_intake_repository.add_ecu(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            role=body.role,
            manufacturer=body.manufacturer,
            family=body.family,
            model=body.model,
            hardware_number=body.hardware_number,
            hardware_revision=body.hardware_revision,
            assembly_part_number=body.assembly_part_number,
            serial_number=body.serial_number,
            mcu_marking=body.mcu_marking,
            software_number=body.software_number,
            calibration_number=body.calibration_number,
            boot_id=body.boot_id,
            coding_id=body.coding_id,
            dataset_id=body.dataset_id,
            provenance_id=body.provenance_id,
            metadata=body.metadata,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, result.case.row_version)
    return _mutation_payload(result)


@router.post("/cases/{case_id}/symptoms", status_code=201)
def add_symptom(
    case_id: UUID,
    body: SymptomCreateRequest,
    request: Request,
    response: Response,
):
    try:
        result = request.app.state.ers_intake_repository.add_symptom(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            description=body.description,
            operating_context=body.operating_context,
            provenance_id=body.provenance_id,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, result.case.row_version)
    return _mutation_payload(result)


@router.post("/cases/{case_id}/dtcs", status_code=201)
def add_dtc(
    case_id: UUID,
    body: DtcCreateRequest,
    request: Request,
    response: Response,
):
    try:
        result = request.app.state.ers_intake_repository.add_dtc(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            protocol=body.protocol,
            ecu_id=body.ecu_id,
            code=body.code,
            spn=body.spn,
            fmi=body.fmi,
            occurrence_count=body.occurrence_count,
            status=body.status,
            raw_text=body.raw_text,
            freeze_frame=body.freeze_frame,
            provenance_id=body.provenance_id,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, result.case.row_version)
    return _mutation_payload(result)


@router.post("/cases/{case_id}/measurements", status_code=201)
def add_measurement(
    case_id: UUID,
    body: MeasurementCreateRequest,
    request: Request,
    response: Response,
):
    try:
        result = request.app.state.ers_intake_repository.add_measurement(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            measurement_type=body.measurement_type,
            value_numeric=body.value_numeric,
            value_text=body.value_text,
            value_json=body.value_json,
            channel=body.channel,
            unit=body.unit,
            ecu_id=body.ecu_id,
            operating_context=body.operating_context,
            method=body.method,
            tool_ref=body.tool_ref,
            provenance_id=body.provenance_id,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, result.case.row_version)
    return _mutation_payload(result)


@router.post("/cases/{case_id}/diagnostic-steps", status_code=201)
def add_diagnostic_step(
    case_id: UUID,
    body: DiagnosticStepCreateRequest,
    request: Request,
    response: Response,
):
    try:
        result = request.app.state.ers_intake_repository.add_diagnostic_step(
            case_id,
            expected_row_version=_expected_version(request),
            actor_id=body.actor_id,
            step_type=body.step_type,
            observation=body.observation,
            hypothesis_text=body.hypothesis_text,
            test=body.test,
            result=body.result,
            next_step=body.next_step,
            status=body.status,
            provenance_id=body.provenance_id,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
    except IntegrityError as exc:
        raise ErsIntegrityConflict() from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_etag(response, result.case.row_version)
    return _mutation_payload(result)
