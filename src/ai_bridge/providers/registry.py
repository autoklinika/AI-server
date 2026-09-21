"""D.3 static inventory, independent of live health, routing and admission.

These configuration descriptors do not replace Stage C adapter describe()/health().
No URLs, credentials, model overrides or arbitrary metadata belong here.
"""
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


DescriptorId = Annotated[str, Field(strict=True, min_length=1, max_length=128,
                                   pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")]
ProviderType = Literal["llm", "media-generation", "agent"]


class _Descriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class CapabilityDescriptor(_Descriptor):
    capability_id: DescriptorId
    # Empty for D.2 metadata-only sentinels, which cannot be assigned a provider.
    provider_types: tuple[ProviderType, ...]

    @model_validator(mode="after")
    def unique_types(self) -> Self:
        if len(set(self.provider_types)) != len(self.provider_types):
            raise ValueError("duplicate capability provider type")
        return self


class NodeDescriptor(_Descriptor):
    node_id: DescriptorId


class LogicalProviderDescriptor(_Descriptor):
    provider_id: DescriptorId
    provider_type: ProviderType
    node_id: DescriptorId
    capabilities: tuple[DescriptorId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("duplicate provider capability")
        return self


class DescriptorRegistry(_Descriptor):
    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    nodes: tuple[NodeDescriptor, ...] = Field(min_length=1)
    capabilities: tuple[CapabilityDescriptor, ...] = Field(min_length=1)
    providers: tuple[LogicalProviderDescriptor, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        for items, key in ((self.nodes, "node_id"),
                           (self.capabilities, "capability_id"),
                           (self.providers, "provider_id")):
            if len({getattr(item, key) for item in items}) != len(items):
                raise ValueError("duplicate descriptor identifier")
        for provider in self.providers:
            self.node(provider.node_id)
            for capability_id in provider.capabilities:
                capability = self.capability(capability_id)
                if provider.provider_type not in capability.provider_types:
                    raise ValueError("incompatible provider capability")
        return self

    def node(self, node_id: str) -> NodeDescriptor:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise ValueError("unknown node descriptor")

    def capability(self, capability_id: str) -> CapabilityDescriptor:
        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise ValueError("unknown capability descriptor")

    def provider(self, provider_id: str) -> LogicalProviderDescriptor:
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        raise ValueError("unknown provider descriptor")

    def validate_assignment(self, provider_id: str, node_id: str,
                            capability_id: str) -> LogicalProviderDescriptor:
        provider = self.provider(provider_id)
        self.node(node_id)
        self.capability(capability_id)
        if provider.node_id != node_id:
            raise ValueError("provider node mismatch")
        if capability_id not in provider.capabilities:
            raise ValueError("provider does not declare capability")
        return provider

    def validate_local_gateway(self, node_id: str) -> None:
        """D.3 config may describe inventory, but cannot change runtime topology.

        Require the existing three bindings/capabilities, independent of order.
        Future multi-node execution needs a separate admission/auth contract.
        """
        expected = local_descriptor_registry(node_id)
        if ({n.node_id for n in self.nodes} != {node_id}
                or {p.provider_id for p in self.providers}
                != {p.provider_id for p in expected.providers}
                or {c.capability_id: set(c.provider_types) for c in self.capabilities}
                != {c.capability_id: set(c.provider_types) for c in expected.capabilities}):
            raise ValueError("D.3 gateway requires the existing single-node inventory")
        for provider in expected.providers:
            configured = self.provider(provider.provider_id)
            if (configured.node_id != node_id
                    or configured.provider_type != provider.provider_type
                    or set(configured.capabilities) != set(provider.capabilities)):
                raise ValueError("D.3 gateway provider binding mismatch")

    def snapshot(self) -> dict[str, object]:
        """Fresh JSON-safe data: configured inventory, never live readiness."""
        return self.model_dump(mode="json")


def local_descriptor_registry(node_id: str = "ai-node-01") -> DescriptorRegistry:
    """Existing backend interfaces; embeddings do not imply an installed model."""
    capabilities = (
        CapabilityDescriptor(capability_id="chat", provider_types=("llm",)),
        CapabilityDescriptor(capability_id="reasoning", provider_types=("llm", "agent")),
        CapabilityDescriptor(capability_id="text-generation", provider_types=("llm",)),
        CapabilityDescriptor(capability_id="structured-generation", provider_types=("llm",)),
        CapabilityDescriptor(capability_id="embeddings", provider_types=("llm",)),
        CapabilityDescriptor(capability_id="image-generation", provider_types=("media-generation",)),
        CapabilityDescriptor(capability_id="image-edit", provider_types=("media-generation",)),
        CapabilityDescriptor(capability_id="video-generation", provider_types=("media-generation",)),
        CapabilityDescriptor(capability_id="tools", provider_types=("agent",)),
        CapabilityDescriptor(capability_id="streaming", provider_types=("llm", "agent")),
        CapabilityDescriptor(capability_id="external-reservation", provider_types=()),
        CapabilityDescriptor(capability_id="unknown", provider_types=()),
    )
    return DescriptorRegistry(
        nodes=(NodeDescriptor(node_id=node_id),),
        capabilities=capabilities,
        providers=tuple(LogicalProviderDescriptor(
            provider_id=provider_id, provider_type=provider_type, node_id=node_id,
            capabilities=tuple(c.capability_id for c in capabilities
                               if provider_type in c.provider_types),
        ) for provider_id, provider_type in (
            ("ollama-local", "llm"), ("comfyui-local", "media-generation"),
            ("hermes-local", "agent"),
        )),
    )
