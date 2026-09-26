"""AI Control Center static shell and narrow Platform API transport.

The browser never talks to infrastructure backends. Remote UI requests are
forwarded only to an explicit read/advisory allowlist on the stable Platform API.
Administrative or arbitrary Platform API calls are intentionally not exposed.
"""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import SecretStr


_STATIC_DIR = Path(__file__).with_name("static").resolve()
_INDEX = _STATIC_DIR / "index.html"
_ALLOWED_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "fc00::/7",
))
_MAX_PROXY_BODY = 1_048_576
_ALLOWED_RESPONSE_HEADERS = {"cache-control", "content-disposition", "content-type", "x-request-id"}

_GET = (
    re.compile(r"^(?:health|observability|operations|jobs|models|systems|apps|benchmarks|traces|system-map|incidents|agents|logs)$"),
    re.compile(r"^jobs/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    re.compile(r"^traces/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    re.compile(r"^incidents/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    re.compile(r"^ecu-repair/cases$"),
    re.compile(r"^ecu-repair/cases/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"),
    re.compile(r"^benchmarks/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/runs(?:/[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?$"),
    re.compile(
        r"^knowledge/documents/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        r"(?:/content)?$"
    ),
)
_POST = {
    "knowledge/search",
    "knowledge/ask",
}

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "manifest-src 'self'; "
        "worker-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _file(path: Path, *, media_type: str | None = None) -> FileResponse:
    headers = dict(_SECURITY_HEADERS)
    # Static filenames are intentionally stable (not content-hashed), so every
    # UI release must revalidate instead of trusting a long browser cache.
    headers["Cache-Control"] = "no-cache, must-revalidate"
    return FileResponse(path, media_type=media_type, headers=headers)


def _peer_allowed(request: Request) -> bool:
    try:
        address = ipaddress.ip_address(request.client.host)
    except (ValueError, AttributeError):
        return False
    return address.is_loopback or any(
        address.version == network.version and address in network
        for network in _ALLOWED_NETWORKS
    )


def _api_allowed(method: str, path: str) -> bool:
    if method == "GET":
        return any(pattern.fullmatch(path) for pattern in _GET)
    return method == "POST" and path in _POST


def create_control_center_app(
    *,
    platform_base_url: str = "http://127.0.0.1:11435/api/v1",
    platform_api_token: SecretStr | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create the GUI shell plus a fail-closed Platform API browser transport."""

    app = FastAPI(
        title="AI Control Center",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.api_route("/api/v1/{api_path:path}", methods=["GET", "POST"], include_in_schema=False)
    async def platform_proxy(api_path: str, request: Request) -> Response:
        if not _peer_allowed(request) or not _api_allowed(request.method, api_path):
            raise HTTPException(status_code=403, detail="control_center_boundary")

        body = await request.body()
        if len(body) > _MAX_PROXY_BODY:
            raise HTTPException(status_code=413, detail="request_too_large")

        headers = {"Accept": request.headers.get("accept", "application/json")}
        if request.method == "POST":
            headers["Content-Type"] = "application/json"
        if platform_api_token is not None:
            headers["Authorization"] = "Bearer " + platform_api_token.get_secret_value()

        timeout = httpx.Timeout(connect=5.0, read=610.0, write=30.0, pool=5.0)
        async with httpx.AsyncClient(
            base_url=platform_base_url.rstrip("/"),
            timeout=timeout,
            transport=upstream_transport,
            trust_env=False,
        ) as client:
            upstream = await client.request(
                request.method,
                "/" + api_path,
                content=body if request.method == "POST" else None,
                headers=headers,
            )

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() in _ALLOWED_RESPONSE_HEADERS
        }
        response_headers.update(_SECURITY_HEADERS)
        response_headers["Cache-Control"] = "no-store"
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> Response:
        return _file(
            _STATIC_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> Response:
        response = _file(_STATIC_DIR / "sw.js", media_type="text/javascript")
        response.headers["Service-Worker-Allowed"] = "/control/"
        return response

    @app.get("/assets/{asset_path:path}", include_in_schema=False)
    async def asset(asset_path: str) -> Response:
        candidate = (_STATIC_DIR / asset_path).resolve()
        if not candidate.is_relative_to(_STATIC_DIR) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="asset_not_found")
        return _file(candidate)

    @app.get("/", include_in_schema=False)
    async def index() -> Response:
        return _file(_INDEX, media_type="text/html")

    @app.get("/{deep_link:path}", include_in_schema=False)
    async def deep_link(deep_link: str) -> Response:
        return _file(_INDEX, media_type="text/html")

    return app
