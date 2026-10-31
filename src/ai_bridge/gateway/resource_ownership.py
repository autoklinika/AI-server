"""P2-A3: candidate-only process/lease correlation, never GPU authorization.

Existing RM lease snapshots contain job IDs but no durable GPU UUID/PID/birth
attestation. Matches from separately injected declarations are only *candidates*
and must never release GPU memory, replace a lease, or classify device safety.
No PID, GPU UUID, boot ID, lease token or worker source is sent to /status.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict

from .resource_gpu_process import ProcessObservation
from .resource_hardware import HardwareReading

_FRESH_NS = 5_000_000_000


@dataclass(frozen=True, slots=True)
class ProcessLeaseClaim:
    """Unverified declaration, NOT a supervisor-authoritative lease binding."""

    job_id: int
    gpu_uuid: str
    pid: int
    start_ticks: int
    boot_id: str


class OwnershipSummary(TypedDict):
    mode: Literal["read_only"]
    result: Literal["UNKNOWN"]
    reason_codes: list[str]
    observed_compute_processes: int
    candidate_lease_process_pairs: int
    unmatched_compute_processes: int
    external_lease_count: int | None
    process_scope: Literal["nvidia_compute_only"]
    lease_process_attribution: Literal["unverified"]
    amd_memory_relation: Literal["unverified"]
    authorizes_execution: Literal[False]


HardwareSource = Callable[[], HardwareReading | None]
ProcessSource = Callable[[], ProcessObservation | None]
ClaimSource = Callable[[], tuple[ProcessLeaseClaim, ...]]


def _unknown(reasons: set[str], *, observed: int = 0, candidates: int = 0,
             unmatched: int = 0, leases: int | None = None) -> OwnershipSummary:
    return {
        "mode": "read_only",
        "result": "UNKNOWN",
        "reason_codes": sorted(reasons),
        "observed_compute_processes": observed,
        "candidate_lease_process_pairs": candidates,
        "unmatched_compute_processes": unmatched,
        "external_lease_count": leases,
        "process_scope": "nvidia_compute_only",
        "lease_process_attribution": "unverified",
        "amd_memory_relation": "unverified",
        "authorizes_execution": False,
    }


def summarize_ownership(
    hardware: HardwareReading | None,
    processes: ProcessObservation | None,
    rm_leases: Mapping[str, object] | None,
    claims: tuple[ProcessLeaseClaim, ...] = (),
    *,
    now_ns: int,
) -> OwnershipSummary:
    """Bounded pure comparison; caller's claim is never a verified proof.

    A 'candidate' requires exact GPU UUID + PID + birth ticks + boot epoch and
    current external-use job ID. The RM snapshot does *not* contain a durable
    owner/process attestation or RM epoch: matching cannot prove ownership.
    """
    reasons: set[str] = {
        "rm_lease_process_identity_unavailable",
        "gpu_context_closure_unverified",
    }
    if hardware is None or not isinstance(hardware, HardwareReading):
        return _unknown(reasons | {"missing_hardware_observation"})
    if processes is None or not isinstance(processes, ProcessObservation):
        return _unknown(reasons | {"missing_compute_observation"})

    if any(d.vendor == "amd" for d in hardware.devices):
        reasons.add("amd_memory_relation_unverified")
        reasons.add("amd_process_ownership_unavailable")
        if hardware.host is not None and any(
            d.vendor == "amd"
            and d.total_bytes is not None
            and d.total_bytes > hardware.host.total_bytes
            for d in hardware.devices
        ):
            reasons.add("amd_driver_vram_exceeds_cpu_visible_ram")
    if hardware.issues:
        reasons.add("incomplete_hardware_inventory")
    if processes.issues:
        reasons.add("partial_process_observation")

    observed = len(processes.processes)
    if (type(now_ns) is not int or now_ns < 0
            or hardware.boot_id is None or processes.boot_id != hardware.boot_id
            or processes.hardware_observed_at_ns != hardware.observed_at_ns):
        return _unknown(
            reasons | {"observation_epoch_mismatch"},
            observed=observed, unmatched=observed,
        )
    if (hardware.observed_at_ns > now_ns or processes.observed_at_ns > now_ns
            or hardware.observed_at_ns < 0 or processes.observed_at_ns < 0
            or now_ns - hardware.observed_at_ns > _FRESH_NS
            or now_ns - processes.observed_at_ns > _FRESH_NS):
        return _unknown(
            reasons | {"stale_or_future_observation"},
            observed=observed, unmatched=observed,
        )

    if (rm_leases is None or not isinstance(rm_leases, Mapping)
            or type(rm_leases.get("lease_count")) is not int
            or not isinstance(rm_leases.get("leases"), list)):
        return _unknown(
            reasons | {"rm_lease_snapshot_unavailable"},
            observed=observed, unmatched=observed,
        )

    rows = rm_leases["leases"]
    lease_count = rm_leases["lease_count"]
    if lease_count != len(rows) or lease_count < 0 or lease_count > 4096:
        return _unknown(
            reasons | {"rm_lease_snapshot_invalid"},
            observed=observed, unmatched=observed,
        )
    external_jobs: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            return _unknown(reasons | {"rm_lease_snapshot_invalid"},
                            observed=observed, unmatched=observed)
        job = row.get("job_id")
        in_use = row.get("external_in_use")
        if type(job) is not int or job <= 0 or job in external_jobs and in_use:
            return _unknown(reasons | {"rm_lease_snapshot_invalid"},
                            observed=observed, unmatched=observed)
        if type(in_use) is not bool:
            return _unknown(reasons | {"rm_lease_snapshot_invalid"},
                            observed=observed, unmatched=observed)
        if in_use:
            external_jobs.add(job)

    known_uuids = {d.identity for d in hardware.devices if d.vendor == "nvidia"}
    by_owner: dict[tuple[str, int, int], set[int]] = {}
    if not isinstance(claims, tuple) or len(claims) > 4096:
        return _unknown(
            reasons | {"invalid_owner_claims"},
            observed=observed, unmatched=observed,
            leases=len(external_jobs),
        )
    for claim in claims:
        if not isinstance(claim, ProcessLeaseClaim) or (
            type(claim.job_id) is not int or claim.job_id not in external_jobs
            or type(claim.pid) is not int or claim.pid <= 1
            or type(claim.start_ticks) is not int or claim.start_ticks <= 0
            or claim.boot_id != hardware.boot_id
            or claim.gpu_uuid not in known_uuids
        ):
            reasons.add("unverifiable_owner_claim")
            continue
        by_owner.setdefault((claim.gpu_uuid, claim.pid, claim.start_ticks), set()).add(
            claim.job_id
        )

    seen: set[tuple[str, int, int]] = set()
    candidates = 0
    for reading in processes.processes:
        if (reading.gpu_uuid not in known_uuids or type(reading.pid) is not int
                or reading.pid <= 1 or type(reading.start_ticks) is not int
                or reading.start_ticks <= 0):
            reasons.add("process_identity_incomplete")
            continue
        key = (reading.gpu_uuid, reading.pid, reading.start_ticks)
        if key in seen:
            reasons.add("duplicate_process_observation")
            continue
        seen.add(key)
        jobs = by_owner.get(key, set())
        if len(jobs) == 1:
            candidates += 1
        elif len(jobs) > 1:
            reasons.add("ambiguous_owner_claims")

    if not claims:
        reasons.add("no_process_lease_claims")
    if candidates:
        reasons.add("candidates_not_verified_ownership")
    return _unknown(
        reasons,
        observed=observed,
        candidates=candidates,
        unmatched=observed - candidates,
        leases=len(external_jobs),
    )


def observe_ownership_sources(
    hardware_source: HardwareSource | None,
    process_source: ProcessSource | None,
    rm_leases: Mapping[str, object] | None,
    *,
    claims_source: ClaimSource | None = None,
    now_ns: Callable[[], int] = time.monotonic_ns,
) -> OwnershipSummary:
    """Read previously collected in-memory samples, never query the OS here."""
    if hardware_source is None or process_source is None:
        return _unknown({"missing_observation_source"})
    try:
        hardware = hardware_source()
        processes = process_source()
        claims = claims_source() if claims_source is not None else ()
        return summarize_ownership(
            hardware, processes, rm_leases, claims, now_ns=now_ns()
        )
    except Exception:
        # Source exceptions may contain secrets. Never return/log exception text.
        return _unknown({"ownership_source_error"})
