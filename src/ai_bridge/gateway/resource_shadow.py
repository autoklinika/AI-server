"""P2-A: read-only, non-authorizing shadow of P1 resource accounting.

The existing RM alone owns jobs, admission, execution, and cleanup.  This
module deliberately has no scheduler, process, device, network or clock access.
A caller must supply all P1 evidence through a trusted in-process adapter.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict

from ai_bridge.providers.accelerators import AcceleratorRegistry
from ai_bridge.providers.resource_topology import ResourceTopology

from .resource_accounting import (
    AssessmentClock,
    RefusalCode,
    ResourceRequest,
    ResourceSnapshot,
    assess_fit,
)


@dataclass(frozen=True, slots=True)
class ShadowInputs:
    """One declared snapshot/request pair; not physical hardware attestation."""

    topology: ResourceTopology
    registry: AcceleratorRegistry
    snapshot: ResourceSnapshot
    request: ResourceRequest
    clock: AssessmentClock


ShadowSource = Callable[[], ShadowInputs | None]
ShadowDecision = Literal["FIT", "DENY", "UNKNOWN"]


class ShadowSummary(TypedDict):
    mode: Literal["observation"]
    result: ShadowDecision
    reason_codes: list[str]
    authorizes_execution: Literal[False]


_INDETERMINATE = frozenset(
    {
        RefusalCode.REVISION,
        RefusalCode.CLOCK_EPOCH,
        RefusalCode.DEVICE_MISMATCH,
        RefusalCode.MISSING_TELEMETRY,
        RefusalCode.GENERATION,
        RefusalCode.STALE,
        RefusalCode.FUTURE,
        RefusalCode.MISSING_CAPACITY,
    }
)


def _summary(result: ShadowDecision, reasons: tuple[str, ...]) -> ShadowSummary:
    return {
        "mode": "observation",
        "result": result,
        "reason_codes": list(reasons),
        "authorizes_execution": False,
    }


def observe_shadow(source: ShadowSource | None) -> ShadowSummary:
    """Evaluate injected data without modifying RM or revealing resource IDs.

    A missing, inconsistent or failing evidence supplier is UNKNOWN, never FIT.
    The output omits raw inputs, device identifiers, exceptions and allocations.
    CancelledError (BaseException) is intentionally not swallowed.
    """
    if source is None:
        return _summary("UNKNOWN", ("missing_evidence",))

    try:
        values = source()
        if not isinstance(values, ShadowInputs):
            return _summary("UNKNOWN", ("missing_evidence",))
        assessment = assess_fit(
            topology=values.topology,
            registry=values.registry,
            snapshot=values.snapshot,
            request=values.request,
            clock=values.clock,
        )
    except (TypeError, ValueError, AttributeError):
        # Includes strict Pydantic validation and inconsistent identity claims.
        return _summary("UNKNOWN", ("invalid_evidence",))
    except Exception:
        # A faulty observational adapter must not interrupt an RM status read.
        # Do not log exception values: an adapter could include private data.
        return _summary("UNKNOWN", ("observer_error",))

    if assessment.fits:
        return _summary("FIT", ())

    codes = frozenset(item.code for item in assessment.diagnostics)
    reasons = tuple(sorted(item.value for item in codes))
    if not codes:
        return _summary("UNKNOWN", ("unexplained_refusal",))
    if codes & _INDETERMINATE:
        return _summary("UNKNOWN", reasons)
    return _summary("DENY", reasons)
