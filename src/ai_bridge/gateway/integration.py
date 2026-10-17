"""N2 boundary: no production adapter exists, so opting in denies execution.

This is deliberately not an AcceleratorAdmission instance or a second queue.
JobMetadata cannot yet be converted into a trusted N1 Claim (worker incarnation,
physical binding and profile are absent). Never manufacture that evidence from
the gateway PID, HTTP headers, residency counters or a successful response.
"""
from dataclasses import dataclass
from typing import Literal

from ai_bridge.providers.accelerators import AcceleratorRegistry
from ai_bridge.providers.registry import DescriptorRegistry


AdmissionStrategy = Literal["legacy", "n2-dev-blocked"]


class AdmissionNotVerified(RuntimeError):
    """Opted-in execution has no trusted N1 integration proof."""


@dataclass(frozen=True)
class N2IntegrationBoundary:
    registry: AcceleratorRegistry

    @classmethod
    def create(cls, registry: AcceleratorRegistry, providers: DescriptorRegistry):
        registry = AcceleratorRegistry.model_validate(registry.model_dump())
        registry.validate_references(providers)
        for binding in registry.provider_bindings:
            provider = providers.provider(binding.provider_id)
            for accelerator_id in binding.accelerator_ids:
                if registry.accelerator(accelerator_id).node_id != provider.node_id:
                    raise ValueError("N2 provider/accelerator node mismatch")
        return cls(registry)

    def require_execution(self) -> None:
        raise AdmissionNotVerified("N2 integration NOT_VERIFIED; execution disabled")

    def snapshot(self) -> dict[str, object]:
        return {
            "strategy": "n2-dev-blocked",
            "verification": "NOT_VERIFIED",
            "execution_enabled": False,
            "owner": "PriorityScheduler",
            "n1_core_started": False,
            "missing_prerequisites": [
                "trusted_cleanup_adapter", "physical_device_binding_and_alias_exclusion",
                "worker_process_incarnation", "tested_profile_compatibility",
                "enforced_memory_isolation", "durable_grant_delivery_and_recovery_bridge",
            ],
            # Unknown is not empty/clean. N2 never acquires or clears ownership.
            "devices": {
                device.accelerator_id: {
                    "verification": "NOT_VERIFIED", "ownership": "UNKNOWN",
                    "shared_owners": None, "exclusive_owner": None,
                    "backend": device.backend, "physical_identity": None,
                } for device in self.registry.accelerators
            },
        }
