from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import time
from typing import Any, Callable
from urllib.parse import urlencode
from uuid import uuid4

import httpx

from ai_bridge.providers.contracts import (
    MediaArtifact,
    MediaGenerationProvider,
    MediaGenerationRequest,
    MediaGenerationResult,
    ProviderDescriptor,
    ProviderHealth,
)


class MediaProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComfyUIWorkflowPlan:
    """Provider-side execution plan resolved from a logical media profile."""

    graph: dict[str, Any]
    output_extensions: tuple[str, ...]
    filename_tag: str
    media_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


WorkflowResolver = Callable[[MediaGenerationRequest], ComfyUIWorkflowPlan]


@dataclass(frozen=True)
class ComfyUIAdapter:
    """MediaGenerationProvider adapter for the local ComfyUI HTTP API.

    Workflow selection is injected through a resolver. Callers use logical
    profile/capability names and do not need to know ComfyUI endpoints.
    """

    base_url: str
    workflow_resolver: WorkflowResolver
    profiles: tuple[str, ...]
    capabilities: tuple[str, ...] = (
        "image-generation",
        "image-edit",
        "video-generation",
    )
    provider_id: str = "comfyui-local"
    node_id: str = "ai-node-01"
    health_timeout_seconds: float = 2.0
    poll_seconds: float = 3.0
    auto_free_memory: bool = True

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("ComfyUIAdapter base_url must not be empty")
        if not callable(self.workflow_resolver):
            raise ValueError("ComfyUIAdapter workflow_resolver must be callable")
        if not self.profiles:
            raise ValueError("ComfyUIAdapter requires at least one logical profile")

    @property
    def _root(self) -> str:
        return self.base_url.rstrip("/")

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self._root}/{path.lstrip('/')}",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:2000]
            raise MediaProviderError(
                f"Media backend returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaProviderError(f"Media backend unavailable: {exc}") from exc

        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise MediaProviderError("Media backend returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise MediaProviderError("Media backend returned unexpected JSON shape")
        return data

    def _request_bytes(self, path: str, *, timeout: float = 300.0) -> bytes:
        try:
            response = httpx.get(
                f"{self._root}/{path.lstrip('/')}",
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MediaProviderError(
                f"Media artifact download returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaProviderError(f"Media artifact download failed: {exc}") from exc
        return response.content

    def object_info(self) -> dict[str, Any]:
        return self._request_json("/object_info", timeout=60.0)

    def generate(self, request: MediaGenerationRequest) -> MediaGenerationResult:
        self._validate_request(request)
        started = time.monotonic()
        plan = self.workflow_resolver(request)
        self._validate_plan(plan)

        submitted = self._request_json(
            "/prompt",
            method="POST",
            payload={"prompt": plan.graph, "client_id": uuid4().hex},
            timeout=60.0,
        )
        prompt_id = str(submitted.get("prompt_id") or "")
        if not prompt_id:
            raise MediaProviderError(
                "Media backend rejected workflow: "
                + json.dumps(submitted, ensure_ascii=False)[:2000]
            )

        record = self._wait_for_output(
            prompt_id,
            extensions=plan.output_extensions,
            timeout_seconds=request.timeout_seconds,
        )
        artifact = self._download_output(
            record,
            output_dir=Path(request.output_dir),
            prompt_id=prompt_id,
            filename_tag=plan.filename_tag,
            media_type=plan.media_type,
        )

        if self.auto_free_memory:
            self.free_memory()

        return MediaGenerationResult(
            request_id=request.request_id,
            capability=request.capability,
            profile=request.profile,
            artifacts=(artifact,),
            provider=self.provider_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
            provider_metadata={
                "prompt_id": prompt_id,
                **plan.metadata,
            },
        )

    def free_memory(self) -> None:
        try:
            self._request_json(
                "/free",
                method="POST",
                payload={"unload_models": True, "free_memory": True},
                timeout=20.0,
            )
        except MediaProviderError:
            # Preserves current media behavior: memory release is best effort
            # and must not turn a successful render into a failed user job.
            pass

    def health(self) -> ProviderHealth:
        try:
            self._request_json("/system_stats", timeout=self.health_timeout_seconds)
            return ProviderHealth(status="ready")
        except MediaProviderError as exc:
            return ProviderHealth(status="unavailable", detail=str(exc))

    def describe(self) -> ProviderDescriptor:
        health = self.health()
        return ProviderDescriptor(
            provider_id=self.provider_id,
            provider_type="media-generation",
            node_id=self.node_id,
            capabilities=self.capabilities,
            models=self.profiles,
            status=health.status,
            metadata={
                "transport": "http",
                "workflow_profiles": self.profiles,
                "artifact_delivery": "download",
            },
        )

    def _wait_for_output(
        self,
        prompt_id: str,
        *,
        extensions: tuple[str, ...],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        wanted = tuple(ext.lower() for ext in extensions)
        while time.monotonic() < deadline:
            history = self._request_json(
                f"/history/{prompt_id}",
                timeout=15.0,
            )
            entry = history.get(prompt_id)
            if isinstance(entry, dict):
                error = self._history_error(entry)
                if error:
                    raise MediaProviderError(f"Media generation failed: {error}")
                record = self._find_output_record(entry, wanted)
                if record is not None:
                    return record
            time.sleep(self.poll_seconds)
        raise MediaProviderError(
            f"Timed out waiting for media generation request {prompt_id}"
        )

    def _download_output(
        self,
        record: dict[str, Any],
        *,
        output_dir: Path,
        prompt_id: str,
        filename_tag: str,
        media_type: str,
    ) -> MediaArtifact:
        filename = str(record.get("filename") or "")
        if not filename:
            raise MediaProviderError("Media output record has no filename")
        subfolder = str(record.get("subfolder") or "")
        file_type = str(record.get("type") or "output")
        params = urlencode(
            {
                "filename": filename,
                "subfolder": subfolder,
                "type": file_type,
            }
        )
        content = self._request_bytes(f"/view?{params}", timeout=300.0)
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix or ".bin"
        target = output_dir / (
            f"{filename_tag}-{time.strftime('%Y%m%d-%H%M%S')}-"
            f"{prompt_id[:8]}{suffix}"
        )
        target.write_bytes(content)
        size = target.stat().st_size
        if size <= 0:
            raise MediaProviderError("Downloaded media artifact is empty")
        return MediaArtifact(
            uri=str(target),
            media_type=media_type,
            size_bytes=size,
            metadata={
                "source_filename": filename,
                "source_subfolder": subfolder,
                "source_type": file_type,
            },
        )

    @staticmethod
    def _history_error(entry: dict[str, Any]) -> str | None:
        status = entry.get("status")
        if not isinstance(status, dict):
            return None
        failures: list[str] = []
        for item in status.get("messages") or []:
            if not isinstance(item, list) or len(item) < 2:
                continue
            if item[0] in {"execution_error", "execution_interrupted"}:
                failures.append(json.dumps(item[1], ensure_ascii=False)[:6000])
        return "\n".join(failures) if failures else None

    @staticmethod
    def _find_output_record(
        entry: dict[str, Any],
        extensions: tuple[str, ...],
    ) -> dict[str, Any] | None:
        outputs = entry.get("outputs")
        if not isinstance(outputs, dict):
            return None
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for value in node_output.values():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    filename = str(item.get("filename") or "")
                    if filename.lower().endswith(extensions):
                        return item
        return None

    def _validate_request(self, request: MediaGenerationRequest) -> None:
        if not request.request_id.strip():
            raise ValueError("MediaGenerationRequest.request_id must not be empty")
        if not request.profile.strip():
            raise ValueError("MediaGenerationRequest.profile must not be empty")
        if request.profile not in self.profiles:
            raise ValueError(f"Unsupported media profile: {request.profile}")
        if request.capability not in self.capabilities:
            raise ValueError(
                f"Unsupported media capability: {request.capability}"
            )
        if not request.prompt.strip():
            raise ValueError("MediaGenerationRequest.prompt must not be empty")
        if not request.output_dir.strip():
            raise ValueError("MediaGenerationRequest.output_dir must not be empty")
        if request.timeout_seconds <= 0:
            raise ValueError("MediaGenerationRequest.timeout_seconds must be > 0")

    @staticmethod
    def _validate_plan(plan: ComfyUIWorkflowPlan) -> None:
        if not isinstance(plan.graph, dict) or not plan.graph:
            raise ValueError("Media workflow graph must be a non-empty mapping")
        if not plan.output_extensions:
            raise ValueError("Media workflow must declare output extensions")
        if not plan.filename_tag.strip():
            raise ValueError("Media workflow filename_tag must not be empty")
        if not plan.media_type.strip():
            raise ValueError("Media workflow media_type must not be empty")
