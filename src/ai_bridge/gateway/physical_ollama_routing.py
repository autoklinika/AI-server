"""DEV-only, strictly static, loopback GPU routing inside the existing Gateway.

Maps an exact model to a physically pinned Ollama endpoint *after* Gateway
priority admission. This does NOT implement N1 grants, shared VRAM budgets,
OS isolation or driver-safe handoff. Disabled unless explicitly configured.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit


class GPUModelRouteRejected(ValueError):
    pass


@dataclass(frozen=True)
class PhysicalOllamaRouter:
    endpoints: dict[str, str]
    model_routes: dict[str, str]

    @classmethod
    def from_json(cls, raw: str | None) -> PhysicalOllamaRouter | None:
        if raw is None or raw == "":
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise GPUModelRouteRejected("invalid physical GPU routing config") from exc
        if not isinstance(value, dict) or set(value) != {"endpoints", "models"}:
            raise GPUModelRouteRejected("endpoints and models required")
        endpoints = value["endpoints"]
        models = value["models"]
        if not isinstance(endpoints, dict) or set(endpoints) != {"amd", "rtx"}:
            raise GPUModelRouteRejected("only explicitly defined amd and rtx endpoints")
        verified_endpoints = {}
        for gpu, addr in endpoints.items():
            if not isinstance(addr, str):
                raise GPUModelRouteRejected("nonstring endpoint")
            parts = urlsplit(addr)
            if (parts.scheme != "http" or parts.hostname != "127.0.0.1"
                or parts.username is not None or parts.password is not None
                or parts.path not in ("", "/") or parts.query or parts.fragment):
                raise GPUModelRouteRejected("GPU target must be bare IPv4 loopback URL")
            try:
                port = parts.port
            except ValueError as exc:
                raise GPUModelRouteRejected("invalid endpoint port") from exc
            if port is None or port < 1024 or port in (11434, 11435) or port > 65535:
                raise GPUModelRouteRejected("endpoint must be an isolated model server")
            verified_endpoints[gpu] = "http://127.0.0.1:"+str(port)
        if len(set(verified_endpoints.values())) != 2:
            raise GPUModelRouteRejected("two GPUs cannot point to the same listener")
        if not isinstance(models, dict) or not models or len(models) > 32:
            raise GPUModelRouteRejected("nonempty model mapping (<=32) required")
        allowed = {}
        for model, target in models.items():
            if (not isinstance(model, str) or not 1 <= len(model) <= 160
                or not all(c.isalnum() or c in "-_./:" for c in model)
                or target not in ("amd", "rtx")):
                raise GPUModelRouteRejected("invalid exact model -> GPU mapping")
            allowed[model] = target
        if "amd" not in set(allowed.values()) or "rtx" not in set(allowed.values()):
            raise GPUModelRouteRejected("model mapping must cover both physical GPUs")
        return cls(verified_endpoints, allowed)

    def resolve(self, request_body: bytes, upstream_path: str) -> tuple[str, str]:
        """Return only a preconfigured trusted URL, never a caller-supplied URL."""
        allowed_paths = {
            "/api/chat", "/api/generate", "/api/embed", "/api/embeddings",
            "/v1/chat/completions", "/v1/embeddings",
        }
        if upstream_path not in allowed_paths:
            raise GPUModelRouteRejected("unsupported model-routed endpoint")
        try:
            payload = json.loads(request_body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GPUModelRouteRejected("model routing needs a valid JSON object") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
            raise GPUModelRouteRejected("explicit model is required")
        model = payload["model"]
        target = self.model_routes.get(model)
        if target is None:
            raise GPUModelRouteRejected("model absent from strict GPU routing map")
        return self.endpoints[target] + upstream_path, target

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "dev_static_loopback",
            "enabled": True,
            "models": dict(self.model_routes),
            "endpoints": dict(self.endpoints),
            "physical_backend_pin": "MUST_BE_VERIFIED_EXTERNALLY",
            "os_enforced_exclusivity": "NOT_VERIFIED",
            "n1_gpu_grants": "NOT_ADMITTED",
            "resource_scheduler": "existing_single_global_queue",
        }
