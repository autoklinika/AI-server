"""Static, same-origin AI Control Center shell.

The browser client talks only to the stable Platform API boundary. This module
serves UI assets and SPA deep-link fallbacks; it contains no platform business
logic and does not proxy privileged backend services.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response


_STATIC_DIR = Path(__file__).with_name("static").resolve()
_INDEX = _STATIC_DIR / "index.html"

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


def _file(path: Path, *, media_type: str | None = None, immutable: bool = False) -> FileResponse:
    headers = dict(_SECURITY_HEADERS)
    headers["Cache-Control"] = "public, max-age=86400" if immutable else "no-cache"
    return FileResponse(path, media_type=media_type, headers=headers)


def create_control_center_app() -> FastAPI:
    """Create the dependency-free GUI shell mounted by the AI Gateway."""

    app = FastAPI(
        title="AI Control Center",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
        return _file(candidate, immutable=True)

    @app.get("/", include_in_schema=False)
    async def index() -> Response:
        return _file(_INDEX, media_type="text/html")

    @app.get("/{deep_link:path}", include_in_schema=False)
    async def deep_link(deep_link: str) -> Response:
        # Stable deep links are resolved client-side. Never map them directly to
        # infrastructure or storage paths.
        return _file(_INDEX, media_type="text/html")

    return app
