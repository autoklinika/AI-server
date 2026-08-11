from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import httpx


_SCHEMA_METADATA_KEYS = {
    "$schema",
    "title",
    "description",
    "default",
    "examples",
}

# These constraints are still enforced by the final Pydantic validation. They are
# intentionally omitted from the sampler grammar because large repetitions and
# nested refs can make llama.cpp/Ollama reject otherwise valid schemas.
_SCHEMA_REPETITION_KEYS = {
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
}


def compact_schema_for_ollama(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a grammar-friendly structural schema without weakening final validation.

    Pydantic emits $defs/$ref for nested models and may include large repetition
    constraints. Ollama converts the schema to a sampler grammar; on some runner
    versions that combination can exceed grammar complexity limits. We inline local
    refs and keep structural constraints (types, required fields, enums,
    additionalProperties) while leaving length/range enforcement to Pydantic after
    generation.

    JSON Schema metadata keywords such as ``title`` and ``description`` are removed
    only when they are schema keywords. Property names are preserved verbatim even
    when a domain field itself is named ``title`` or ``description``.
    """

    source = deepcopy(schema)
    definitions = source.get("$defs", {})

    def resolve(node: Any, stack: tuple[str, ...] = ()) -> Any:
        if isinstance(node, list):
            return [resolve(item, stack) for item in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref = node["$ref"]
            prefix = "#/$defs/"
            if not isinstance(ref, str) or not ref.startswith(prefix):
                raise ValueError(f"Unsupported JSON Schema reference for Ollama: {ref!r}")
            name = ref[len(prefix) :]
            if name in stack:
                raise ValueError(f"Recursive JSON Schema reference is not supported: {ref}")
            target = definitions.get(name)
            if not isinstance(target, dict):
                raise ValueError(f"JSON Schema reference not found: {ref}")
            merged = deepcopy(target)
            for key, value in node.items():
                if key != "$ref":
                    merged[key] = value
            return resolve(merged, (*stack, name))

        compact: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$defs" or key in _SCHEMA_METADATA_KEYS or key in _SCHEMA_REPETITION_KEYS:
                continue
            if key == "const":
                compact["enum"] = [value]
                continue
            if key == "properties":
                if not isinstance(value, dict):
                    raise ValueError("JSON Schema properties must be an object")
                # Property names are domain data, not schema metadata. Do not run
                # names such as 'title' or 'description' through metadata filtering.
                compact["properties"] = {
                    property_name: resolve(property_schema, stack)
                    for property_name, property_schema in value.items()
                }
                continue
            compact[key] = resolve(value, stack)
        return compact

    resolved = resolve(source)
    if not isinstance(resolved, dict):
        raise ValueError("Root JSON Schema must be an object")
    return resolved


@dataclass(frozen=True)
class OllamaChatResult:
    content: str
    model: str
    prompt_eval_count: int | None
    eval_count: int | None
    total_duration_ns: int | None


@dataclass(frozen=True)
class OllamaClient:
    base_url: str
    timeout_seconds: float = 300.0
    availability_timeout_seconds: float = 2.0

    def is_available(self) -> bool:
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}/api/tags",
                timeout=self.availability_timeout_seconds,
            )
            return response.is_success
        except httpx.HTTPError:
            return False

    def chat_structured(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
        think: bool = False,
        temperature: float = 0.0,
    ) -> OllamaChatResult:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": response_schema,
            "think": think,
            "options": {"temperature": temperature},
        }
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:2000]
            raise RuntimeError(
                f"Ollama returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama unavailable: {exc}") from exc

        data = response.json()
        message = data.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama response does not contain message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama response does not contain structured content")

        def optional_int(name: str) -> int | None:
            value = data.get(name)
            return value if isinstance(value, int) else None

        return OllamaChatResult(
            content=content,
            model=str(data.get("model", model)),
            prompt_eval_count=optional_int("prompt_eval_count"),
            eval_count=optional_int("eval_count"),
            total_duration_ns=optional_int("total_duration"),
        )
