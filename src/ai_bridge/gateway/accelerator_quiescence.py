"""N4 DEV structural protocol only: no I/O, attestation, adapter or admission.

All supplied evidence is UNTRUSTED, including records naming a kernel source.
Authority names specify the boundary N5 would have to independently verify.
The bounded, single-use assessment ledger is NOT an ownership coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import math
import re
from threading import Lock
from typing import Literal
from uuid import UUID

from .accelerator_evidence import PciIdentity


class Authority(Enum):
    SUPERVISOR = "authoritative_supervisor_required"
    RUNTIME = "owned_runtime_required"
    BACKEND = "authoritative_device_backend_required"
    KERNEL = "kernel_required"


class Stage(Enum):
    PREVENT_SUBMIT = "prevent_new_submit"
    SCOPE = "complete_descendants_and_delegated_handles"
    STREAMS = "all_runtimes_all_streams"
    DRAIN = "owner_device_work_drained"
    TEARDOWN = "owner_fd_context_and_deferred_cleanup"
    ISOLATION = "survivors_preserved"


REQUIRED = (Authority.SUPERVISOR, Authority.SUPERVISOR, Authority.RUNTIME,
            Authority.BACKEND, Authority.KERNEL, Authority.KERNEL)


@dataclass(frozen=True)
class Owner:
    worker_id: str
    pid: int
    birth_ticks: int
    scope_id: str  # Proposed immutable supervisor scope identity, not a cgroup path.
    scope_generation: int
    lease_id: str
    lease_generation: int


@dataclass(frozen=True)
class Binding:
    nonce: str
    rm_epoch: str
    device: PciIdentity
    device_generation: int  # Proposed reset/hotplug/rebind generation, NOT N3 observation.
    owner: Owner
    mode: Literal["SHARED", "EXCLUSIVE"]
    survivors: tuple[Owner, ...]
    ownership_revision: int


@dataclass(frozen=True)
class Challenge:
    binding: Binding
    issued_at: float  # Caller supplies monotonic time in one RM epoch.
    deadline: float


@dataclass(frozen=True)
class Evidence:
    binding: Binding
    stage: Stage
    required_authority: Authority
    source_id: str  # Claimed source, never authenticated here.
    observed_at: float
    complete: bool
    # Cannot be changed to TRUSTED by a caller or configuration flag.
    provenance: Literal["UNTRUSTED"] = "UNTRUSTED"


@dataclass(frozen=True)
class Closure:
    binding: Binding
    members: tuple[Owner, ...]  # Owner plus every descendant/delegated submitter.
    process_readers_complete: bool
    scope_sealed: bool
    runtime_inventory_complete: bool
    device_mapping_complete: bool  # KFD FD alone cannot satisfy this.
    unknown_submitters: int
    unsynchronized_streams: int
    pending_owner_work: int
    active_owner_contexts: int
    active_owner_fds: int
    deferred_owner_cleanup: int
    survivors: tuple[Owner, ...]
    survivor_isolation_preserved: bool


@dataclass(frozen=True)
class Assessment:
    status: Literal["ready_for_trusted_verification", "unverified"]
    reason: str

    @property
    def decision(self) -> Literal["DENY"]:
        return "DENY"

    @property
    def authorizes_release(self) -> Literal[False]:
        return False

    @property
    def authorizes_admission(self) -> Literal[False]:
        return False

    def __bool__(self) -> bool:
        raise TypeError("N4 assessment is not an authorization boolean")


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _time(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _bounded(value: object) -> bool:
    """Reject malformed containers/strings before comparisons or hashing."""
    if isinstance(value, Enum):
        return True
    if type(value) is str:
        return 0 < len(value) <= 512
    if type(value) is tuple:
        return len(value) <= 128 and all(_bounded(v) for v in value)
    if is_dataclass(value) and not isinstance(value, type):
        return all(_bounded(getattr(value, f.name)) for f in fields(value))
    return type(value) in (bool, int, float) and (type(value) is not float or math.isfinite(value))


def _owner(o: Owner) -> bool:
    return (type(o) is Owner and all(type(v) is str and v for v in
            (o.worker_id, o.scope_id, o.lease_id)) and all(_integer(v, 1) for v in
            (o.pid, o.birth_ticks, o.scope_generation, o.lease_generation)) and o.pid > 1)


def _binding(b: Binding) -> bool:
    if type(b) is not Binding or not _bounded(b) or type(b.device) is not PciIdentity:
        return False
    d = b.device
    try:
        boot_valid = str(UUID(d.boot_id)) == d.boot_id
    except (ValueError, AttributeError, TypeError):
        return False
    bdf = r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]"
    return bool(boot_valid and type(b.nonce) is str and len(b.nonce) >= 32
                and type(b.rm_epoch) is str and b.rm_epoch
                and type(d.bdf) is str and re.fullmatch(bdf, d.bdf)
                and type(d.sysfs_path) is str
                and re.fullmatch(rf"/sys/devices/pci[0-9a-f]{{4}}:[0-9a-f]{{2}}(?:/{bdf})+", d.sysfs_path)
                and d.sysfs_path.endswith("/" + d.bdf)
                and d.vendor in ("0x1002", "0x8086", "0x10de")
                and type(d.device) is str and re.fullmatch(r"0x[0-9a-f]{4}", d.device)
                and _integer(b.device_generation, 1) and _integer(b.ownership_revision)
                and _owner(b.owner) and b.mode in ("SHARED", "EXCLUSIVE")
                and type(b.survivors) is tuple and all(_owner(o) for o in b.survivors)
                and len({o.lease_id for o in (b.owner, *b.survivors)}) == 1 + len(b.survivors)
                and len({o.pid for o in (b.owner, *b.survivors)}) == 1 + len(b.survivors)
                and (b.mode == "SHARED" or not b.survivors))


class QuiescenceAssessor:
    """One-shot structural checks; instantiate with a fresh RM epoch on restart.

    Caller supplies authoritative *expected* identities/revision and monotonic
    time, never values copied from an HTTP certificate. Even a dishonest caller
    cannot obtain authorization. No expiry releases ownership. No hardware reads.
    Lock serializes assess/cancel; all attempts consume their challenge. A lease
    can be assessed only once in this ledger, including after failure/cancel.
    """

    def __init__(self, rm_epoch: str, *, capacity: int = 128):
        if type(rm_epoch) is not str or not 0 < len(rm_epoch) <= 512 or not _integer(capacity, 1) or capacity > 4096:
            raise ValueError("invalid epoch or capacity")
        self._epoch = rm_epoch
        self._capacity = capacity
        self._challenges: dict[str, Challenge] = {}
        self._used: set[str] = set()
        self._owners: set[tuple[PciIdentity, Owner]] = set()
        self._lock = Lock()

    def register(self, challenge: Challenge) -> None:
        with self._lock:
            if (type(challenge) is not Challenge or not _binding(challenge.binding)
                    or challenge.binding.rm_epoch != self._epoch
                    or not _time(challenge.issued_at) or not _time(challenge.deadline)
                    or not 0 < challenge.deadline - challenge.issued_at <= 60):
                raise ValueError("invalid challenge")
            b = challenge.binding
            key = (b.device, b.owner)
            if len(self._challenges) >= self._capacity or b.nonce in self._challenges or key in self._owners:
                raise ValueError("duplicate challenge/owner or ledger full")
            self._challenges[b.nonce] = challenge
            self._owners.add(key)

    def cancel(self, nonce: str) -> None:
        with self._lock:
            if type(nonce) is str and nonce in self._challenges:
                self._used.add(nonce)

    def assess(self, nonce: str, evidence: tuple[Evidence, ...], closure: Closure,
               *, current: Binding, now: float) -> Assessment:
        with self._lock:
            deny = lambda reason: Assessment("unverified", reason)
            if type(nonce) is not str or nonce not in self._challenges or nonce in self._used:
                return deny("unknown, cancelled or replayed challenge")
            self._used.add(nonce)
            c = self._challenges[nonce]
            if not _binding(current) or current != c.binding:
                return deny("identity, epoch, device, owner set or revision changed")
            if not _time(now) or not c.issued_at <= now < c.deadline:
                return deny("expired or invalid clock")
            if type(evidence) is not tuple or len(evidence) != len(Stage):
                return deny("partial lifecycle")
            previous = c.issued_at
            for e, stage, authority in zip(evidence, Stage, REQUIRED):
                if (type(e) is not Evidence or not _bounded(e) or not _binding(e.binding)
                        or e.binding != current or e.stage is not stage
                        or e.required_authority is not authority or type(e.source_id) is not str
                        or e.provenance != "UNTRUSTED" or e.complete is not True
                        or not _time(e.observed_at) or not previous < e.observed_at <= now):
                    return deny("invalid, stale, unordered or mismatched lifecycle evidence")
                previous = e.observed_at
            if type(closure) is not Closure or not _bounded(closure):
                return deny("invalid closure")
            if (not _binding(closure.binding) or closure.binding != current
                    or type(closure.members) is not tuple or not closure.members
                    or not all(_owner(o) for o in closure.members)
                    or current.owner not in closure.members
                    or len({o.pid for o in closure.members}) != len(closure.members)
                    or any(o.pid == survivor.pid or o.worker_id == survivor.worker_id
                           or o.lease_id == survivor.lease_id
                           for o in closure.members for survivor in current.survivors)
                    or closure.survivors != current.survivors):
                return deny("incomplete scope or survivor mismatch")
            for name in ("process_readers_complete", "scope_sealed", "runtime_inventory_complete",
                         "device_mapping_complete", "survivor_isolation_preserved"):
                if getattr(closure, name) is not True:
                    return deny("unknown scope, runtime, mapping or isolation")
            for name in ("unknown_submitters", "unsynchronized_streams", "pending_owner_work",
                         "active_owner_contexts", "active_owner_fds", "deferred_owner_cleanup"):
                if not _integer(getattr(closure, name)) or getattr(closure, name) != 0:
                    return deny("owner closure incomplete or unknown submitters")
            return Assessment("ready_for_trusted_verification",
                              "structural data only; trusted kernel/runtime proof unavailable")
