from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ai_bridge.settings import Settings, get_settings
from ai_bridge.providers.registry import local_descriptor_registry

from .admission import WorkloadBinding, DIRECT_READS, external_workload, http_workload
from .priority import PriorityClass, priority_for_class
from .jobs import JobLifecycle, JobMetadata
from .resource_leases import (
    ResourceLeaseNotActive,
    ResourceLeaseNotAllowed,
    ResourceLeaseNotFound,
    ResourceLeaseRegistry,
)
from .residency import GPUResidency, ResidencyError
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


def _class_priority(payload: dict, default: int) -> int:
    if "priority_class" not in payload:
        return default
    try:
        return priority_for_class(payload["priority_class"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid priority_class") from exc


def _consume_priority_class(body: bytes, default: int) -> tuple[bytes, int, PriorityClass | None]:
    """Consume Gateway metadata while preserving legacy bodies byte-for-byte."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body, default, None
    if not isinstance(payload, dict) or "priority_class" not in payload:
        return body, default, None
    priority = _class_priority(payload, default)
    semantic = PriorityClass("infrastructure" if payload["priority_class"] == "critical" else payload["priority_class"])
    del payload["priority_class"]
    return json.dumps(payload).encode("utf-8"), priority, semantic


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
        "X-AI-Request-Id": ticket.request_id,
        "X-AI-Job-Id": ticket.platform_job_id,
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
    residency_transport: httpx.AsyncBaseTransport | None = None,
    platform_provider=None,
    platform_policy=None,
) -> FastAPI:
    resolved = settings or get_settings()
    registry = resolved.gateway_registry or local_descriptor_registry(resolved.node_id)
    registry.validate_local_gateway(resolved.node_id)
    upstream_provider = registry.provider("ollama-local")
    scheduler = PriorityScheduler(
        max_concurrency=resolved.gateway_max_concurrency,
        max_queue_size=resolved.gateway_max_queue_size,
        registry=registry,
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
        ) as client, httpx.AsyncClient(
            base_url=resolved.gateway_comfy_url.rstrip("/"), timeout=10,
            transport=residency_transport, trust_env=False,
        ) as comfy:
            residency = GPUResidency(client, comfy, resolved.gateway_gpu_marker,
                                     timeout=resolved.gateway_gpu_transition_timeout)
            resource_leases.residency = residency
            scheduler.admission_blocked = residency.state == "blocked"
            from ai_bridge.platform.provider import GatewayLLMAdapter
            app.state.platform_provider = platform_provider or GatewayLLMAdapter(
                client, resolved.ollama_model, resolved.node_id, resolved.gateway_health_timeout_seconds
            )
            app.state.upstream = client
            app.state.scheduler = scheduler
            app.state.resource_leases = resource_leases
            app.state.descriptor_registry = registry

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
        if (request.method, upstream_path) not in DIRECT_READS:
            raise HTTPException(status_code=400, detail="admission required")
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
                type(exc).__name__,
            )
            return JSONResponse(status_code=502, content={"error": "ollama_unavailable"})
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_forward_response_headers(upstream),
        )

    async def leased_ticket(
        request: Request, workload: WorkloadBinding,
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
            ticket = await resource_leases.begin_use(lease_id, workload=workload)
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
        except (ResourceLeaseNotActive, ResourceLeaseNotAllowed):
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
        body, class_priority, semantic = _consume_priority_class(body, default_priority)
        priority = _parse_priority(request, class_priority)
        source = _parse_source(request, default_source)
        workload = http_workload(registry, upstream_path, ventilation=default_source == "ventilation")
        metadata = JobMetadata(
            domain="wvc" if default_source == "ventilation" else "shared",
            capability=workload.capability,
            priority_class=semantic,
            workload=(workload,),
        )
        client: httpx.AsyncClient = request.app.state.upstream
        lease_id, ticket, release_after, lease_error = await leased_ticket(request, workload)
        if lease_error is not None:
            return lease_error
        if ticket is None:
            try:
                ticket = await scheduler.acquire(priority=priority, source=source, metadata=metadata)
            except SchedulerQueueFull:
                return await queue_full_response()

        async def finish(state: JobLifecycle) -> None:
            if lease_id:
                # The lease describes the reservation, not each provider call.
                await resource_leases.end_use(lease_id, release=release_after)
            else:
                await scheduler.release(ticket, state=state)

        def unavailable() -> Response:
            LOGGER.warning("AI Gateway upstream unavailable path=%s", upstream_path)
            return JSONResponse(status_code=502, content={"error": "ollama_unavailable"},
                                headers=_diagnostic_headers(ticket))

        state = JobLifecycle.COMPLETED
        if not _requests_stream(body):
            try:
                if not lease_id:
                    await scheduler.mark_running(ticket.job_id, provider=upstream_provider.provider_id,
                                                 node=upstream_provider.node_id)
                upstream = await client.request(
                    request.method, upstream_path, content=body,
                    headers=_forward_request_headers(request),
                )
                if upstream.is_error:
                    state = JobLifecycle.FAILED
            except asyncio.CancelledError:
                state = JobLifecycle.CANCELLED
                raise
            except httpx.RequestError:
                state = JobLifecycle.FAILED
                return unavailable()
            except BaseException:
                state = JobLifecycle.FAILED
                raise
            finally:
                await finish(state)
            headers = _forward_response_headers(upstream)
            headers.update(_diagnostic_headers(ticket))
            return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)

        stream_context = client.stream(
            request.method, upstream_path, content=body,
            headers=_forward_request_headers(request),
        )
        try:
            if not lease_id:
                await scheduler.mark_running(ticket.job_id, provider=upstream_provider.provider_id,
                                             node=upstream_provider.node_id)
            upstream = await stream_context.__aenter__()
        except asyncio.CancelledError:
            await finish(JobLifecycle.CANCELLED)
            raise
        except httpx.RequestError:
            await finish(JobLifecycle.FAILED)
            return unavailable()
        except BaseException:
            await finish(JobLifecycle.FAILED)
            raise

        async def iterator():
            outcome = JobLifecycle.FAILED if upstream.is_error else JobLifecycle.COMPLETED
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            except (asyncio.CancelledError, GeneratorExit):
                outcome = JobLifecycle.CANCELLED
                raise
            except BaseException:
                outcome = JobLifecycle.FAILED
                raise
            finally:
                try:
                    await stream_context.__aexit__(None, None, None)
                except asyncio.CancelledError:
                    outcome = JobLifecycle.CANCELLED
                    raise
                except BaseException:
                    if outcome == JobLifecycle.COMPLETED:
                        outcome = JobLifecycle.FAILED
                    raise
                finally:
                    await finish(outcome)

        headers = _forward_response_headers(upstream)
        headers.update(_diagnostic_headers(ticket))
        return StreamingResponse(iterator(), status_code=upstream.status_code, headers=headers)

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
        snapshot["gpu_residency"] = resource_leases.residency.snapshot()
        snapshot["resource_leases"] = await resource_leases.snapshot()
        snapshot["registry"] = registry.snapshot()
        return snapshot

    # External Resource Manager API. It is intentionally served by the existing
    # localhost-only AI Gateway and contains no prompt or response content.
    @app.exception_handler(ResidencyError)
    @app.exception_handler(httpx.HTTPError)
    @app.exception_handler(TimeoutError)
    async def residency_failure(request: Request, exc: Exception):
        return JSONResponse(status_code=503, content={"error": "gpu_transition_failed_closed"})

    @app.post("/resource/leases")
    async def create_resource_lease(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON object required")

        source = str(body.get("source") or "external").strip()[:64] or "external"
        class_priority = _class_priority(body, resolved.gateway_priority_interactive)
        try:
            priority = int(body.get("priority", class_priority))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid priority") from exc
        if not -1000 <= priority <= 1000:
            raise HTTPException(
                status_code=400,
                detail="priority must be between -1000 and 1000",
            )

        try:
            workload = external_workload(registry, body.get("workload", "external"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid workload") from exc
        try:
            payload = await resource_leases.create(
                priority=priority,
                source=source,
                metadata=JobMetadata(capability="external-reservation", workload=workload, priority_class=(
                    PriorityClass("infrastructure" if body["priority_class"] == "critical" else body["priority_class"])
                    if "priority_class" in body else None)),
            )
        except SchedulerQueueFull:
            return await queue_full_response()
        return JSONResponse(status_code=201, content=payload)

    @app.post("/resource/leases/{lease_id}/uses")
    async def begin_external_use(lease_id: str, request: Request) -> Response:
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"provider", "capability"}:
                raise ValueError()
            # Only the existing external media executor is supported. Embedding
            # execution still enters through scheduled HTTP.
            if body["provider"] != "comfyui-local":
                raise ValueError()
            provider = registry.provider(body["provider"])
            workload = WorkloadBinding(provider.provider_id, provider.node_id, body["capability"])
            workload.validate(registry)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="invalid external workload")
        try:
            use_id = await resource_leases.begin_external_use(lease_id, workload)
        except ResourceLeaseNotFound:
            return JSONResponse(status_code=404, content={"error": "resource_lease_not_found"})
        except (ResourceLeaseNotActive, ResourceLeaseNotAllowed):
            return JSONResponse(status_code=409, content={"error": "resource_lease_not_available"})
        return JSONResponse(status_code=201, content={"use_id": use_id})

    @app.delete("/resource/leases/{lease_id}/uses/{use_id}")
    async def end_external_use(lease_id: str, use_id: str) -> dict[str, bool]:
        try:
            return {"released": await resource_leases.end_external_use(lease_id, use_id)}
        except ResourceLeaseNotActive:
            raise HTTPException(status_code=409, detail="GPU transition in progress")

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

    from ai_bridge.platform.api import create_platform_app
    app.mount("/api/v1", create_platform_app(app, resolved, platform_policy))
    return app


app = create_gateway_app()
