from uuid import UUID
from fastapi import APIRouter, Request, Query
from .schemas import Manifest, LinkRequest, UnlinkRequest, FindingRequest, AnalysisRequest, AIContext

router = APIRouter(prefix="/api/v1/crt", tags=["crt"])


def repo(request):
    return request.app.state.crt_repository


@router.post("/manifests")
def import_manifest(payload: Manifest, request: Request):
    return repo(request).import_manifest(payload)


@router.get("/sessions")
def sessions(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), project_id: str | None = Query(None, max_length=160)):
    return repo(request).sessions(limit, offset, project_id)


@router.get("/sessions/{session_id}")
def session(session_id: UUID, request: Request):
    return repo(request).get(session_id)


@router.get("/sessions/{session_id}/ers-links")
def links(session_id: UUID, request: Request):
    return repo(request).links(session_id)


@router.post("/sessions/{session_id}/ers-links")
def link(session_id: UUID, payload: LinkRequest, request: Request):
    return repo(request).link(session_id, **payload.model_dump())


@router.post("/sessions/{session_id}/ers-links/{case_id}/{role}/unlink")
def unlink(session_id: UUID, case_id: UUID, role: str, payload: UnlinkRequest, request: Request):
    return repo(request).link(session_id, case_id, role, payload.actor_id, active=False)


@router.post("/sessions/{session_id}/findings", status_code=201)
def finding(session_id: UUID, payload: FindingRequest, request: Request):
    return repo(request).finding(session_id, payload)


@router.get("/sessions/{session_id}/findings")
def findings(session_id: UUID, request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return repo(request).findings(session_id, limit, offset)


@router.post("/sessions/{session_id}/signal-hypothesis", status_code=201)
def analyze(session_id: UUID, payload: AIContext | AnalysisRequest, request: Request):
    if isinstance(payload, AIContext):
        payload = AnalysisRequest(context=payload, actor_id="crt-context-import")
    return request.app.state.crt_analysis.analyze(session_id, payload)
