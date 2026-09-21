"""Descriptor-validated, metadata-only admission plans for the local shared pool."""
from dataclasses import dataclass

from ai_bridge.providers.registry import DescriptorRegistry


@dataclass(frozen=True, slots=True)
class WorkloadBinding:
    provider: str
    node: str
    capability: str

    def validate(self, registry: DescriptorRegistry) -> None:
        registry.validate_assignment(self.provider, self.node, self.capability)


def binding(registry: DescriptorRegistry, provider: str, capability: str) -> WorkloadBinding:
    descriptor = registry.provider(provider)
    result = WorkloadBinding(provider, descriptor.node_id, capability)
    result.validate(registry)
    return result


def external_workload(registry: DescriptorRegistry, name: str = "external") -> tuple[WorkloadBinding, ...]:
    """Legacy external reservations may span Qwen and ComfyUI, never Hermes itself.

    Profiles declare permitted work, not proof of execution or provider readiness.
    No model selection or future embedding implementation is introduced here.
    """
    llm = ("chat", "reasoning", "text-generation", "structured-generation")
    profiles = {
        "llm": (("ollama-local", llm),),
        "embeddings": (("ollama-local", ("embeddings",)),),
        "media-image": (("ollama-local", llm), ("comfyui-local", ("image-generation", "image-edit"))),
        "media-video": (("ollama-local", llm), ("comfyui-local", ("video-generation",))),
        "external": (("ollama-local", (*llm, "embeddings")),
                     ("comfyui-local", ("image-generation", "image-edit", "video-generation"))),
    }
    if not isinstance(name, str) or name not in profiles:
        raise ValueError("invalid workload")
    return tuple(binding(registry, provider, capability)
                 for provider, capabilities in profiles[name] for capability in capabilities)


def http_workload(registry: DescriptorRegistry, path: str, *, ventilation: bool = False) -> WorkloadBinding:
    capabilities = {"/api/chat": "chat", "/api/generate": "text-generation",
                    "/v1/chat/completions": "chat", "/api/embed": "embeddings",
                    "/api/embeddings": "embeddings", "/v1/embeddings": "embeddings"}
    if path not in capabilities:
        raise ValueError("unsupported scheduled route")
    return binding(registry, "ollama-local", "reasoning" if ventilation else capabilities[path])


# Direct forwarding is limited to inexpensive inventory reads, even if a future
# route accidentally calls the direct helper for inference.
DIRECT_READS = frozenset({("GET", "/api/tags"), ("GET", "/v1/models")})
