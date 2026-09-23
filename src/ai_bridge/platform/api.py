"""Platform API v1. Legacy Gateway routes intentionally remain independent."""
import asyncio
import hmac
import ipaddress
import json
import logging
import re
from dataclasses import asdict
from time import monotonic
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from ai_bridge.gateway.admission import WorkloadBinding
from ai_bridge.gateway.jobs import JobLifecycle, JobMetadata
from ai_bridge.gateway.priority import PriorityClass, priority_for_class
from ai_bridge.gateway.scheduler import SchedulerQueueFull
from ai_bridge.providers.contracts import LLMRequest
from ai_bridge.platform.observability import PlatformRequestMetrics, job_metrics, runtime_resources

LOGGER = logging.getLogger(__name__)
ID = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Context(Contract):
    request_id: ID | None = None
    domain: ID = "shared"
    actor_id: ID | None = None
    session_id: ID | None = None
    case_id: ID | None = None
    current_view: ID | None = None
    context_ref: ID | None = None


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=65536)


class AIRequest(Contract):
    schema_version: Literal[1] = 1
    capability: ID = "reasoning"
    model: Literal["reasoning-main"] = "reasoning-main"
    context: Context = Field(default_factory=Context)
    priority_class: Literal["infrastructure", "interactive-high", "interactive", "normal",
                            "background", "maintenance"] = "interactive"
    messages: list[Message] = Field(min_length=1, max_length=64)
    response_schema: dict | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    timeout_seconds: float = Field(default=300, gt=0, le=600)


class APIError(Exception):
    def __init__(self, status, code, retryable=False):
        self.status, self.code, self.retryable = status, code, retryable


class LocalServicePolicy:
    """Initial service-wide policy; actor_id is context, never authentication.

    With a configured token every caller must authenticate. Without one only
    direct loopback peers are allowed. Forwarded headers are never trusted here.
    Network exposure still requires deployment policy; legacy routes stay local.
    """
    def __init__(self, token=None):
        self.token = token

    async def authorize(self, request):
        if self.token is not None:
            expected = "Bearer " + self.token.get_secret_value()
            if not hmac.compare_digest(request.headers.get("authorization", "").encode(),
                                       expected.encode()):
                raise APIError(401, "unauthorized")
        else:
            try:
                allowed = ipaddress.ip_address(request.client.host).is_loopback
            except (ValueError, AttributeError):
                allowed = False
            if not allowed:
                raise APIError(403, "forbidden")


def create_platform_app(gateway, settings, policy=None):
    api = FastAPI(title="Platform API", version="1", docs_url=None, redoc_url=None)
    policy = policy or LocalServicePolicy(settings.platform_api_token)
    metrics = PlatformRequestMetrics()
    api.state.observability = metrics

    def error(request, status, code, retryable=False):
        request.state.error_code = code
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": code.replace("_", " ").capitalize(),
            "request_id": request.state.request_id, "retryable": retryable, "details": {}}})

    @api.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = "req_" + uuid4().hex
        request.state.error_code = None
        started = metrics.begin()
        response = None
        try:
            raw = request.headers.get("x-request-id")
            if raw is not None:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", raw):
                    raise APIError(400, "invalid_request")
                request.state.request_id = raw
            await policy.authorize(request)
            response = await call_next(request)
        except APIError as exc:
            response = error(request, exc.status, exc.code, exc.retryable)
        except Exception:
            response = error(request, 500, "internal_error")
        finally:
            status = response.status_code if response is not None else 499
            code = request.state.error_code
            if code is None and status >= 500:
                code = "server_error"
            elif code is None and status >= 400:
                code = "client_error"
            elapsed = metrics.finish(started, status, code)
            route = getattr(request.scope.get("route"), "path", "unmatched")
            LOGGER.info("PLATFORM_REQUEST %s", json.dumps({
                "request_id": request.state.request_id, "method": request.method,
                "route": route, "status": status, "duration_ms": round(elapsed, 3),
                "error_class": code}, separators=(",", ":"), sort_keys=True))
        if response is not None:
            response.headers["X-Request-Id"] = request.state.request_id
        return response

    @api.exception_handler(APIError)
    async def api_error(request, exc):
        return error(request, exc.status, exc.code, exc.retryable)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(request, 400, "invalid_request")

    @api.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, "not_found" if exc.status_code == 404 else "invalid_request")

    def envelope(request, **data):
        return {"schema_version": 1, "request_id": request.state.request_id, **data}

    async def jobs():
        snapshot = await gateway.state.scheduler.snapshot()
        return ([item["job"] for item in snapshot["active"] + snapshot["queued"]]
                + snapshot["recent_jobs"])

    def public_job(job):
        # Explicit allowlist: never expose source headers, payloads or lease credentials.
        keys = ("job_id", "request_id", "domain", "capability", "priority_class", "state",
                "assigned_provider", "assigned_node", "created_at", "queued_at", "admitted_at",
                "started_at", "finished_at")
        return {"schema_version": 1, **{key: job[key] for key in keys}}

    @api.get("/jobs")
    async def list_jobs(request: Request):
        return envelope(request, jobs=[public_job(job) for job in await jobs()],
                        retention={"persistent": False, "terminal_limit": 128})

    @api.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        job = next((job for job in await jobs() if job["job_id"] == job_id), None)
        if job is None:
            raise APIError(404, "not_found")
        return envelope(request, job=public_job(job))

    @api.get("/models")
    async def models(request: Request):
        return envelope(request, models=[{"logical_id": "reasoning-main",
                        "capabilities": ["chat", "reasoning", "structured-generation"],
                        "streaming": False}])

    @api.get("/systems")
    async def systems(request: Request):
        return envelope(request, systems=[{"system_id": "wvc", "integration": "compatibility",
                        "control_policy": "advisory_only"},
                        {"system_id": "telegram", "integration": "compatibility"},
                        {"system_id": "discord", "integration": "compatibility"},
                        {"system_id": "media", "integration": "compatibility"}])

    async def operational_snapshot():
        scheduler = await gateway.state.scheduler.snapshot()
        leases = await gateway.state.resource_leases.snapshot()
        gpu = gateway.state.resource_leases.residency.snapshot()
        cleanup = ((gpu.get("cleanup_evidence") or {}).get("residency") or {})
        provider = gateway.state.platform_provider
        return {
            "resource_manager": {
                "admission_blocked": scheduler["admission_blocked"],
                "active": scheduler["active_count"], "queued": scheduler["queued_count"],
                "max_concurrency": scheduler["max_concurrency"],
                "max_queue_size": scheduler["max_queue_size"],
            },
            "resource_leases": {"active": leases["lease_count"]},
            "gpu_residency": {
                "state": gpu.get("state"), "recovery_required": gpu.get("recovery_required"),
                "queue_running": cleanup.get("queue_running"),
                "queue_pending": cleanup.get("queue_pending"),
                "loaded_models": cleanup.get("loaded_models"),
                "cleanup_pending": cleanup.get("cleanup_pending"),
            },
            "execution": {"provider": provider.provider_id, "node": provider.node_id,
                          "logical_model": "reasoning-main"},
            "jobs": job_metrics(scheduler),
            "retention": {"persistent": False,
                          "recent_job_count": len(scheduler["recent_jobs"]),
                          "terminal_limit": gateway.state.scheduler.history_limit},
            "process": runtime_resources(),
        }

    @api.get("/observability")
    async def observability(request: Request):
        snapshot = await operational_snapshot()
        return envelope(request, status="ok" if not snapshot["resource_manager"]["admission_blocked"]
                        else "blocked", requests=metrics.snapshot(), **snapshot)

    @api.get("/health")
    async def health(request: Request):
        snapshot = await operational_snapshot()
        try:
            async with asyncio.timeout(settings.gateway_health_timeout_seconds):
                inference_ready = await gateway.state.platform_provider.ready()
        except Exception:
            inference_ready = False
        ready = inference_ready and not snapshot["resource_manager"]["admission_blocked"]
        return envelope(request, status="ready" if ready else "degraded", liveness=True,
                        readiness=ready, components={
                            "resource_manager": {
                                "status": "blocked" if snapshot["resource_manager"]["admission_blocked"] else "ready",
                                "active": snapshot["resource_manager"]["active"],
                                "queued": snapshot["resource_manager"]["queued"],
                            },
                            "resource_leases": snapshot["resource_leases"],
                            "gpu_residency": snapshot["gpu_residency"],
                            "inference": {"status": "ready" if inference_ready else "unavailable"},
                        }, compatibility_health="not_probed")

    @api.post("/ai")
    async def ai(body: AIRequest, request: Request):
        if body.context.request_id:
            if request.headers.get("x-request-id") not in (None, body.context.request_id):
                raise APIError(400, "invalid_request")
            request.state.request_id = body.context.request_id
        if body.capability not in ("chat", "reasoning", "structured-generation"):
            raise APIError(503, "capability_unavailable")
        if body.capability == "structured-generation" and body.response_schema is None:
            raise APIError(400, "invalid_request")
        scheduler = gateway.state.scheduler
        provider = gateway.state.platform_provider
        metadata = JobMetadata(request_id=request.state.request_id, domain=body.context.domain,
                               capability=body.capability, priority_class=PriorityClass(body.priority_class),
                               workload=(WorkloadBinding(provider.provider_id, provider.node_id,
                                                         body.capability),))
        ticket = None
        outcome = JobLifecycle.FAILED
        start = monotonic()
        try:
            async with asyncio.timeout(body.timeout_seconds):
                ticket = await scheduler.acquire(priority=priority_for_class(body.priority_class),
                                                 source="platform-v1", metadata=metadata)
                await scheduler.mark_running(ticket.job_id, provider=provider.provider_id,
                                             node=provider.node_id)
                result = await provider.generate(LLMRequest(
                    request_id=metadata.request_id, capability=body.capability,
                    messages=[item.model_dump() for item in body.messages],
                    response_schema=body.response_schema, temperature=body.temperature,
                    context=body.context.model_dump(exclude_none=True)))
                outcome = JobLifecycle.COMPLETED
        except SchedulerQueueFull:
            raise APIError(429, "queue_full", True) from None
        except TimeoutError:
            outcome = JobLifecycle.EXPIRED
            raise APIError(504, "deadline_exceeded", True) from None
        except asyncio.CancelledError:
            outcome = JobLifecycle.CANCELLED
            raise
        except Exception:
            raise APIError(503, "provider_unavailable", True) from None
        finally:
            if ticket is not None:
                await scheduler.release(ticket, state=outcome)
        return envelope(request, job_id=ticket.platform_job_id, state="completed",
                        content=result.content, finish_reason=result.finish_reason,
                        usage=asdict(result.usage), execution={"provider": provider.provider_id,
                        "model": body.model, "node": provider.node_id,
                        "queue_wait_ms": round(ticket.wait_ms, 3),
                        "duration_ms": round((monotonic() - start) * 1000, 3)})

    return api
