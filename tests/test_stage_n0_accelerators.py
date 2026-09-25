import httpx
import pytest

from ai_bridge.providers.accelerators import (
    AcceleratorDescriptor,
    AcceleratorRegistry,
    AcceleratorRequirements,
    ProviderAcceleratorBinding,
    local_accelerator_registry,
)
from ai_bridge.providers.registry import local_descriptor_registry
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client


def test_default_accelerator_inventory_is_explicit_and_compatible():
    providers = local_descriptor_registry()
    inventory = local_accelerator_registry()
    inventory.validate_references(providers)
    assert inventory.schema_version == 1
    assert [item.accelerator_id for item in inventory.accelerators] == ["local-primary"]
    primary = inventory.accelerator("local-primary")
    assert primary.kind == "integrated"
    assert primary.memory_class == "unified"
    assert primary.backend == "unknown"
    assert inventory.candidates("hermes-local") == ()


def test_constraints_fail_closed_when_memory_is_unknown():
    inventory = local_accelerator_registry()
    assert inventory.candidates(
        "ollama-local",
        AcceleratorRequirements(memory_classes=("unified",)),
    )
    assert inventory.candidates(
        "ollama-local",
        AcceleratorRequirements(backends=("cuda",)),
    ) == ()
    assert inventory.candidates(
        "ollama-local",
        AcceleratorRequirements(min_memory_bytes=1),
    ) == ()


def test_future_discrete_inventory_can_be_described_without_activation():
    providers = local_descriptor_registry()
    inventory = AcceleratorRegistry(
        accelerators=(
            *local_accelerator_registry().accelerators,
            AcceleratorDescriptor(
                accelerator_id="external-01",
                node_id="ai-node-01",
                kind="discrete",
                backend="cuda",
                memory_class="dedicated",
                total_memory_bytes=48 * 1024**3,
                workload_classes=("llm", "media-generation"),
                enabled=False,
            ),
        ),
        provider_bindings=(
            ProviderAcceleratorBinding(
                provider_id="ollama-local",
                accelerator_ids=("local-primary", "external-01"),
            ),
            ProviderAcceleratorBinding(
                provider_id="comfyui-local",
                accelerator_ids=("local-primary", "external-01"),
            ),
        ),
    )
    inventory.validate_references(providers)
    assert [item.accelerator_id for item in inventory.candidates("ollama-local")] == [
        "local-primary"
    ]


def test_invalid_provider_or_node_binding_fails_closed():
    providers = local_descriptor_registry()
    inventory = AcceleratorRegistry(
        accelerators=(AcceleratorDescriptor(
            accelerator_id="bad",
            node_id="other-node",
            kind="discrete",
            backend="cuda",
            memory_class="dedicated",
            workload_classes=("llm",),
        ),),
        provider_bindings=(ProviderAcceleratorBinding(
            provider_id="missing-provider",
            accelerator_ids=("bad",),
        ),),
    )
    with pytest.raises(ValueError):
        inventory.validate_references(providers)


@pytest.mark.anyio
async def test_gateway_status_exposes_n0_inventory_and_legacy_gpu_alias(tmp_path):
    settings = Settings(
        _env_file=None,
        gateway_gpu_marker=tmp_path / "gpu.blocked",
    )
    app = create_gateway_app(
        settings,
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": []})
        ),
        residency_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})
        ),
    )
    async with api_client(app) as client:
        status = (await client.get("/status")).json()
        assert status["accelerators"]["schema_version"] == 1
        assert status["accelerators"]["primary_accelerator_id"] == "local-primary"
        primary = status["accelerators"]["devices"][0]
        assert primary["accelerator_id"] == "local-primary"
        assert primary["residency"] == status["gpu_residency"]
        health = (await client.get("/health")).json()
        assert health["accelerators"]["devices"][0]["residency"] == health["gpu_residency"]
