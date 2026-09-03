from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ai_bridge.settings import Settings, get_settings

from .scheduler import PriorityScheduler, SchedulerQueueFull, SchedulerTicket


LOGGER = logging.getLogger(__name__)
_PRIORITY_HEADER = "x-ai-priority"
_SOURCE_HEADER = "x-ai-source"
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
            yield

    app = FastAPI(
        title="AI Gateway",
        version="1",
        description=(
            "Priority admission gateway in front of the local Ollama inference server."
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

        if _requests_stream(body):
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
                await scheduler.release(ticket)
                LOGGER.warning(
                    "AI Gateway upstream unavailable path=%s error=%s",
                    upstream_path,
                    exc,
                )
                return JSONResponse(status_code=502, content={"error": "ollama_unavailable"})
            except BaseException:
                await scheduler.release(ticket)
                raise

            async def iterator():
                try:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                finally:
                    await stream_context.__aexit__(None, None, None)
                    await scheduler.release(ticket)

            headers = _forward_response_headers(upstream)
            headers.update(_diagnostic_headers(ticket))
            return StreamingResponse(
                iterator(),
                status_code=upstream.status_code,
                headers=headers,
            )

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
            return JSONResponse(status_code=502, content={"error": "ollama_unavailable"})

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
        return await scheduler.snapshot()

    @app.get("/api/tags")
    async def ollama_tags(request: Request) -> Response:
        return await proxy_direct(request, "/api/tags")

    @app.get("/clients/ventilation/api/tags")
    async def ventilation_ollama_tags(request: Request) -> Response:
        return await proxy_direct(request, "/api/tags")

    @app.get("/v1/models")
    async def openai_models(request: Request) -> Response:
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

    @app.post("/v1/embeddings")
    async def openai_embeddings(request: Request) -> Response:
        return await proxy_scheduled(
            request,
            "/v1/embeddings",
            default_priority=resolved.gateway_priority_normal,
            default_source="embedding",
        )

    return app


app = create_gateway_app()
