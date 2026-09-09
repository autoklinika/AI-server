from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ai_bridge.settings import Settings, get_settings

from .resource_leases import (
    ResourceLeaseNotActive,
    ResourceLeaseNotFound,
    ResourceLeaseRegistry,
)
from .scheduler import PriorityScheduler, SchedulerQueueFull, SchedulerTicket


LOGGER = logging.getLogger(__name__)
_PRIORITY_HEADER = "x-ai-priority"
_SOURCE_HEADER = "x-ai-source"
_RESOURCE_LEASE_HEADER = "x-ai-resource-lease"
_RESOURCE_LEASE_RELEASE_HEADER = "x-ai-resource-lease-release"
_REQUEST_HEADER_ALLOWLIST = {"accept", "authorization", "content-type"}
_RESPONSE_HEADER_ALLOWLIST = {
    "cache-control",
    "content-encoding",
    "content-type",
    "x-request-id",
}


def _parse_priority(request: Request, default: int) -> int:
    raw = request.headers.get(_PRIORITY_HEADER)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid X-AI-Priority header") from exc
    if not -1000 <= value <= 1000:
        raise HTTPException(
            status_code=400,
            detail="X-AI-Priority must be between -1000 and 1000",
        )
    return value


def _parse_source(request: Request, default: str) -> str:
    value = (request.headers.get(_SOURCE_HEADER) or default).strip()
    if not value:
        return default
    return value[:64]


def _requests_stream(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("stream") is True


def _forward_request_headers(request: Request) -> dict[str, str]:
    """Forward only upstream-safe headers; Resource Manager control stays local."""

    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() in _REQUEST_HEADER_ALLOWLIST
    }


def _forward_response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() in _RESPONSE_HEADER_ALLOWLIST
    }


def _diagnostic_headers(ticket: SchedulerTicket) -> dict[str, str]:
    return {
        "X-AI-Gateway-Job-Id": str(ticket.job_id),
        "X-AI-Gateway-Priority": str(ticket.priority),
        "X-AI-Gateway-Wait-Ms": f"{ticket.wait_ms:.3f}",
    }


def _truthy_header(request: Request, name: str) -> bool:
    return (request.headers.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def create_gateway_app(
    settings: Settings | None = None,
    *,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    scheduler = PriorityScheduler(
        max_concurrency=resolved.gateway_max_concurrency,
        max_queue_size=resolved.gateway_max_queue_size,
    )
    resource_leases = ResourceLeaseRegistry(
        scheduler,
        ttl_seconds=resolved.gateway_external_lease_ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        timeout = httpx.Timeout(
            connect=resolved.gateway_connect_timeout_seconds,
            read=resolved.gateway_upstream_timeout_seconds,
            write=resolved.gateway_upstream_timeout_seconds,
            pool=resolved.gateway_connect_timeout_seconds,
        )
        async with httpx.AsyncClient(
            base_url=resolved.ollama_url.rstrip("/"),
            timeout=timeout,
            transport=upstream_transport,
            trust_env=False,
        ) as client:
            app.state.upstream = client
            app.state.scheduler = scheduler
            app.state.resource_leases = resource_leases

            # External media workers heartbeat their reservation. Reap only idle
            # leases whose worker disappeared so a crash cannot wedge the single
            # global AI slot forever.
            stop_reaper = asyncio.Event()

            async def lease_reaper() -> None:
                interval = max(
                    1.0,
                    min(10.0, resolved.gateway_external_lease_ttl_seconds / 3.0),
                )
                while not stop_reaper.is_set():
                    try:
                        await asyncio.wait_for(stop_reaper.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        removed = await resource_leases.reap_expired()
                        if removed:
                            LOGGER.warning(
                                "Reaped %d expired external resource lease(s)",
                                removed,
                            )

            reaper_task = asyncio.create_task(lease_reaper())
            try:
                yield
            finally:
                stop_reaper.set()
                reaper_task.cancel()
                try:
                    await reaper_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="AI Gateway",
        version="2",
        description=(
            "Priority admission gateway and global local-AI resource manager."
        ),
        lifespan=lifespan,
    )

    async def queue_full_response() -> JSONResponse:
        snapshot = await scheduler.snapshot()
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "1"},
            content={
                "error": "ai_gateway_queue_full",
                "queued": snapshot["queued_count"],
                "max_queue_size": snapshot["max_queue_size"],
            },
        )

    async def proxy_direct(request: Request, upstream_path: str) -> Response:
        client: httpx.AsyncClient = request.app.state.upstream
        try:
            upstream = await client.request(
                request.method,
                upstream_path,
                content=await request.body(),
                headers=_forward_request_headers(request),
            )
        except httpx.RequestError as exc:
            LOGGER.warning(
                "AI Gateway upstream unavailable path=%s error=%s",
                upstream_path,
                exc,
            )
            return JSONResponse(status_code=502, content={"error": "ollama_unavailable"})
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_forward_response_headers(upstream),
        )

    async def leased_ticket(
        request: Request,
    ) -> tuple[str | None, SchedulerTicket | None, bool, Response | None]:
        """Resolve an already-admitted external lease for this upstream request.

        The request must not enter the scheduler again: media workers deliberately
        keep one lease while first calling Qwen and then ComfyUI. Re-acquiring here
        with max_concurrency=1 would deadlock against the worker's own reservation.
        """

        lease_id = (request.headers.get(_RESOURCE_LEASE_HEADER) or "").strip()
        if not lease_id:
            return None, None, False, None

        release_after = _truthy_header(request, _RESOURCE_LEASE_RELEASE_HEADER)
        try:
            ticket = await resource_leases.begin_use(lease_id)
        except ResourceLeaseNotFound:
            return (
                lease_id,
                None,
                release_after,
                JSONResponse(
                    status_code=404,
                    content={"error": "resource_lease_not_found"},
                ),
            )
        except ResourceLeaseNotActive:
            return (
                lease_id,
                None,
                release_after,
                JSONResponse(
                    status_code=409,
                    content={"error": "resource_lease_not_active"},
                ),
            )
        return lease_id, ticket, release_after, None

    async def proxy_scheduled(
        request: Request,
        upstream_path: str,
        *,
        default_priority: int,
        default_source: str,
    ) -> Response:
        body = await request.body()
        priority = _parse_priority(request, default_priority)
        source = _parse_source(request, default_source)
        client: httpx.AsyncClient = request.app.state.upstream

        lease_id, ticket, release_after, lease_error = await leased_ticket(request)
        if lease_error is not None:
            return lease_error

        if _requests_stream(body):
            if ticket is None:
                try:
                    ticket = await scheduler.acquire(priority=priority, source=source)
                except SchedulerQueueFull:
                    return await queue_full_response()

            stream_context = client.stream(
                request.method,
                upstream_path,
                content=body,
                headers=_forward_request_headers(request),
            )
            try:
                upstream = await stream_context.__aenter__()
            except httpx.RequestError as exc:
                if lease_id:
                    await resource_leases.end_use(
                        lease_id,
                        release=release_after,
                    )
                else:
                    await scheduler.release(ticket)
                LOGGER.warning(
                    "AI Gateway upstream unavailable path=%s error=%s",
                    upstream_path,
                    exc,
                )
                return JSONResponse(
                    status_code=502,
                    content={"error": "ollama_unavailable"},
                )
            except BaseException:
                if lease_id:
                    await resource_leases.end_use(
                        lease_id,
                        release=release_after,
                    )
                else:
                    await scheduler.release(ticket)
                raise

            async def iterator():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    await stream_context.__aexit__(None, None, None)
                    if lease_id:
                        await resource_leases.end_use(
                            lease_id,
                            release=release_after,
                        )
                    else:
                        await scheduler.release(ticket)

            headers = _forward_response_headers(upstream)
            headers.update(_diagnostic_headers(ticket))
            return StreamingResponse(
                iterator(),
                status_code=upstream.status_code,
                headers=headers,
            )

        if ticket is not None:
            # The external worker owns the scheduler slot. It may keep the lease
            # after this Qwen call (media) or request automatic release (normal
            # Telegram conversation) through the control header.
            try:
                upstream = await client.request(
                    request.method,
                    upstream_path,
                    content=body,
                    headers=_forward_request_headers(request),
                )
            except httpx.RequestError as exc:
                LOGGER.warning(
                    "AI Gateway upstream unavailable path=%s error=%s",
                    upstream_path,
                    exc,
                )
                return JSONResponse(
                    status_code=502,
                    content={"error": "ollama_unavailable"},
                )
            finally:
                await resource_leases.end_use(
                    lease_id,
                    release=release_after,
                )
        else:
            try:
                async with scheduler.slot(priority=priority, source=source) as ticket:
                    upstream = await client.request(
                        request.method,
                        upstream_path,
                        content=body,
                        headers=_forward_request_headers(request),
                    )
            except SchedulerQueueFull:
                return await queue_full_response()
            except httpx.RequestError as exc:
                LOGGER.warning(
                    "AI Gateway upstream unavailable path=%s error=%s",
                    upstream_path,
                    exc,
                )
                return JSONResponse(
                    status_code=502,
                    content={"error": "ollama_unavailable"},
                )

        headers = _forward_response_headers(upstream)
        headers.update(_diagnostic_headers(ticket))
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
        )

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        client: httpx.AsyncClient = request.app.state.upstream
        try:
            upstream = await client.get(
                "/api/tags",
                timeout=resolved.gateway_health_timeout_seconds,
            )
            ollama = "ok" if upstream.is_success else f"http_{upstream.status_code}"
        except httpx.RequestError:
            ollama = "unavailable"
        snapshot = await scheduler.snapshot()
        return {
            "status": "ok" if ollama == "ok" else "degraded",
            "ollama": ollama,
            "scheduler": snapshot,
        }

    @app.get("/status")
    async def status() -> dict[str, object]:
        snapshot = await scheduler.snapshot()
        snapshot["resource_leases"] = await resource_leases.snapshot()
        return snapshot

    # External Resource Manager API. It is intentionally served by the existing
    # localhost-only AI Gateway and contains no prompt or response content.
    @app.post("/resource/leases")
    async def create_resource_lease(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")

        source = str(body.get("source") or "external").strip()[:64] or "external"
        try:
            priority = int(body.get("priority", resolved.gateway_priority_interactive))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid priority") from exc
        if not -1000 <= priority <= 1000:
            raise HTTPException(
                status_code=400,
                detail="priority must be between -1000 and 1000",
            )

        try:
            payload = await resource_leases.create(
                priority=priority,
                source=source,
            )
        except SchedulerQueueFull:
            return await queue_full_response()
        return JSONResponse(status_code=201, content=payload)

    @app.get("/resource/leases/{lease_id}")
    async def resource_lease_status(lease_id: str) -> dict[str, object]:
        try:
            return await resource_leases.describe(lease_id)
        except ResourceLeaseNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/resource/leases/{lease_id}/heartbeat")
    async def resource_lease_heartbeat(lease_id: str) -> dict[str, object]:
        try:
            return await resource_leases.heartbeat(lease_id)
        except ResourceLeaseNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/resource/leases/{lease_id}")
    async def release_resource_lease(lease_id: str) -> dict[str, bool]:
        return {"released": await resource_leases.release(lease_id)}

    @app.get("/api/tags")
    async def ollama_tags(request: Request) -> Response:
        return await proxy_direct(request, "/api/tags")

    @app.get("/clients/ventilation/api/tags")
    async def ventilation_ollama_tags(request: Request) -> Response:
        return await proxy_direct(request, "/api/tags")

    @app.get("/v1/models")
    async def openai_models(request: Request) -> Response:
        return await proxy_direct(request, "/v1/models")

    @app.get("/clients/hermes/v1/models")
    async def hermes_openai_models(request: Request) -> Response:
        return await proxy_direct(request, "/v1/models")

    @app.post("/api/chat")
    async def ollama_chat(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/api/chat",
            default_priority=resolved.gateway_priority_normal,
            default_source="ollama-native",
        )

    @app.post("/clients/ventilation/api/chat")
    async def ventilation_ollama_chat(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/api/chat",
            default_priority=resolved.gateway_priority_ventilation,
            default_source="ventilation",
        )

    @app.post("/api/generate")
    async def ollama_generate(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/api/generate",
            default_priority=resolved.gateway_priority_normal,
            default_source="ollama-native",
        )

    @app.post("/api/embed")
    async def ollama_embed(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/api/embed",
            default_priority=resolved.gateway_priority_normal,
            default_source="embedding",
        )

    @app.post("/api/embeddings")
    async def ollama_embeddings(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/api/embeddings",
            default_priority=resolved.gateway_priority_normal,
            default_source="embedding",
        )

    @app.post("/v1/chat/completions")
    async def openai_chat_completions(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/v1/chat/completions",
            default_priority=resolved.gateway_priority_interactive,
            default_source="interactive",
        )

    @app.post("/clients/hermes/v1/chat/completions")
    async def hermes_openai_chat_completions(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/v1/chat/completions",
            default_priority=resolved.gateway_priority_interactive,
            default_source="hermes",
        )

    @app.post("/v1/embeddings")
    async def openai_embeddings(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/v1/embeddings",
            default_priority=resolved.gateway_priority_normal,
            default_source="embedding",
        )

    @app.post("/clients/hermes/v1/embeddings")
    async def hermes_openai_embeddings(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/v1/embeddings",
            default_priority=resolved.gateway_priority_interactive,
            default_source="hermes",
        )

    return app


app = create_gateway_app()
