"""N1 DEV-only RM admission core. No routes, hardware access or production adapter.

Single event-loop owner; synchronous transitions cannot interleave. Every grant
is journaled before delivery. Every process start/restart begins BLOCKED, even
with an empty journal. Only an injected trusted adapter can establish safety.
Never run alongside another coordinator for the same physical devices.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai_bridge.providers.accelerators import (
    AcceleratorDescriptor, AcceleratorRegistry, AcceleratorRequirements,
)
from ai_bridge.providers.registry import DescriptorId, DescriptorRegistry


class AdmissionError(RuntimeError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProcessIdentity(_Model):
    boot_id: DescriptorId
    pid: int = Field(strict=True, gt=1)
    birth_ticks: int = Field(strict=True, gt=0)
    scope: DescriptorId


class Profile(_Model):
    profile_id: DescriptorId
    provider_id: DescriptorId
    workload_class: DescriptorId
    reserved_bytes: int = Field(strict=True, gt=0)


class PoolPolicy(_Model):
    accelerator_id: DescriptorId
    adapter_id: DescriptorId
    memory_limit_bytes: int = Field(strict=True, gt=0)
    profiles: tuple[Profile, ...] = Field(min_length=1)
    sharing_enabled: bool = Field(default=False, strict=True)
    max_shared: int = Field(default=2, strict=True, ge=2, le=128)
    # Explicit tested unordered pairs, including (profile, profile).
    compatible_pairs: tuple[tuple[DescriptorId, DescriptorId], ...] = ()
    compatibility_report: str = ""


class Claim(_Model):
    request_id: DescriptorId
    accelerator_id: DescriptorId
    provider_id: DescriptorId
    profile_id: DescriptorId
    process: ProcessIdentity
    mode: Literal["SHARED", "EXCLUSIVE"] = "EXCLUSIVE"
    priority: int = Field(default=10, strict=True, ge=0, le=1000)
    requirements: AcceleratorRequirements = Field(default_factory=AcceleratorRequirements)


@dataclass(frozen=True)
class Grant:
    epoch: str
    generation: int
    lease_id: str
    resource_id: str
    claim: Claim
    reserved_bytes: int


@dataclass(frozen=True)
class Verification:
    """Trusted verifier must bind evidence to this entire challenge.

    For release, prove this worker incarnation cannot submit further work, all
    its device work/cleanup finished and remaining owners remain isolated. For
    recovery, prove the device and all journaled prior owners safe. Counters,
    free VRAM, unload/job completion and empty runtime inventories do not suffice.
    """
    nonce: str
    epoch: str
    device: AcceleratorDescriptor
    journal_sha256: str
    journal: bytes
    grant: Grant | None
    remaining: tuple[Grant, ...]


class SafetyAdapter(Protocol):
    adapter_id: str
    backend: str

    def can_start(self, device: AcceleratorDescriptor, claim: Claim,
                  active: tuple[Grant, ...]) -> bool:
        """Verify new AND active worker identities, binding and isolation.

        No I/O that yields, no reentry into this core, no process/GPU startup.
        A production implementation requires trusted fresh evidence here.
        """
        ...

    async def verify(self, challenge: Verification) -> bool:
        """Return exactly True only on complete device/incarnation scoped proof."""
        ...


@dataclass
class _Pool:
    policy: PoolPolicy
    device: AcceleratorDescriptor
    adapter: SafetyAdapter
    blocked: bool = True
    verifying: bool = False
    revision: int = 0
    generation: int = 0
    active: dict[str, Grant] = field(default_factory=dict)


@dataclass
class _Request:
    claim: Claim
    sequence: int
    future: asyncio.Future[Grant]
    state: Literal["queued", "granted", "cancelled", "released"] = "queued"
    grant: Grant | None = None


class AcceleratorAdmission:
    """Explicitly constructed DEV core, NOT connected to PriorityScheduler.

    Lower priority numbers win, FIFO ties. A waiting predecessor bars later
    claims on its device, including shared claims behind an exclusive. Other
    devices proceed. No preemption, automatic expiry of ownership or retries.
    Request IDs are never reused within this bounded instance.
    """

    def __init__(self, registry: AcceleratorRegistry, providers: DescriptorRegistry,
                 policies: tuple[PoolPolicy, ...], adapters: tuple[SafetyAdapter, ...],
                 journal: Path, *, enabled: bool = False, max_requests: int = 4096,
                 max_queue: int = 128):
        if enabled is not True:
            raise AdmissionError("N1 DEV admission is disabled")
        if (type(max_requests) is not int or max_requests < 1
                or type(max_queue) is not int or max_queue < 1):
            raise ValueError("invalid admission bounds")
        registry = AcceleratorRegistry.model_validate(registry.model_dump())
        policies = tuple(PoolPolicy.model_validate(p.model_dump()) for p in policies)
        registry.validate_references(providers)
        self._loop = asyncio.get_running_loop()
        self._registry = registry
        self._epoch = uuid4().hex
        self._requests: dict[str, _Request] = {}
        self._pools: dict[str, _Pool] = {}
        self._max_requests, self._max_queue = max_requests, max_queue
        adapter_map = {a.adapter_id: a for a in adapters}
        if len(adapter_map) != len(adapters):
            raise ValueError("duplicate adapter")
        for policy in policies:
            device = registry.accelerator(policy.accelerator_id)
            adapter = adapter_map.get(policy.adapter_id)
            if (device.accelerator_id in self._pools or not device.enabled
                    or device.locality != "local" or device.backend == "unknown"
                    or device.total_memory_bytes is None
                    or policy.memory_limit_bytes > device.total_memory_bytes
                    or adapter is None or adapter.backend != device.backend):
                raise ValueError("unsupported or ambiguous pool configuration")
            profiles = {p.profile_id: p for p in policy.profiles}
            if len(profiles) != len(policy.profiles):
                raise ValueError("duplicate profile")
            for p in policy.profiles:
                if (device not in registry.candidates(p.provider_id)
                        or providers.provider(p.provider_id).node_id != device.node_id
                        or p.workload_class not in device.workload_classes
                        or p.reserved_bytes > policy.memory_limit_bytes):
                    raise ValueError("invalid profile binding or budget")
            pairs = [frozenset(pair) for pair in policy.compatible_pairs]
            if (len(set(pairs)) != len(pairs)
                    or any(not pair <= profiles.keys() for pair in pairs)
                    or (policy.sharing_enabled and (not pairs or not policy.compatibility_report.strip()))):
                raise ValueError("sharing requires tested compatibility declarations")
            self._pools[device.accelerator_id] = _Pool(policy, device, adapter)
        if not self._pools:
            raise ValueError("no explicitly activated pools")
        # The directory must already exist in the DEV workspace. Lock the journal
        # inode for this component's lifetime; never unlink/replace it.
        self._journal = journal.open("a+b")
        try:
            fcntl.flock(self._journal.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._write({"event": "boot", "epoch": self._epoch})
            fd = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException:
            self._journal.close()
            raise
        self._closed = False

    def _check(self) -> None:
        if self._closed or asyncio.get_running_loop() is not self._loop:
            raise AdmissionError("closed core or wrong event loop")

    def _write(self, event: dict) -> None:
        try:
            self._journal.write((json.dumps(event, sort_keys=True) + "\n").encode())
            self._journal.flush()
            os.fsync(self._journal.fileno())
        except BaseException:
            for pool in self._pools.values():
                pool.blocked = True
                pool.revision += 1
            raise

    def submit(self, claim: Claim) -> None:
        self._check()
        # Revalidate even instances built with model_construct/model_copy.
        claim = Claim.model_validate(claim.model_dump())
        if claim.request_id in self._requests:
            raise AdmissionError("duplicate request ID")
        if (len(self._requests) >= self._max_requests
                or sum(r.state == "queued" for r in self._requests.values()) >= self._max_queue):
            raise AdmissionError("admission bounds reached")
        pool = self._pools.get(claim.accelerator_id)
        if pool is None or pool.device not in self._registry.candidates(claim.provider_id, claim.requirements):
            raise AdmissionError("no bound accelerator satisfies requirements")
        profile = next((p for p in pool.policy.profiles if p.profile_id == claim.profile_id), None)
        if profile is None or profile.provider_id != claim.provider_id:
            raise AdmissionError("unapproved profile/provider")
        if claim.mode == "SHARED" and (not pool.policy.sharing_enabled
                or (claim.profile_id, claim.profile_id) not in pool.policy.compatible_pairs):
            raise AdmissionError("sharing disabled or profile lacks tested self-compatibility")
        identity = (claim.process.boot_id, claim.process.pid, claim.process.birth_ticks)
        if any(r.state in ("queued", "granted")
               and (r.claim.process.boot_id, r.claim.process.pid, r.claim.process.birth_ticks) == identity
               for r in self._requests.values()):
            raise AdmissionError("worker incarnation already owns a claim")
        self._requests[claim.request_id] = _Request(claim, len(self._requests), self._loop.create_future())
        self._dispatch()

    async def wait(self, request_id: str, *, timeout: float | None = None) -> Grant:
        self._check()
        request = self._requests[request_id]
        if timeout is not None and (type(timeout) not in (int, float)
                                    or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")
        try:
            async with asyncio.timeout(timeout):
                return await asyncio.shield(request.future)
        except BaseException:
            self.cancel(request_id)
            raise

    def cancel(self, request_id: str) -> None:
        """Also used for worker crash/partial startup. Granted ownership stays pinned."""
        self._check()
        request = self._requests[request_id]
        if request.state == "queued":
            request.state = "cancelled"
            request.future.cancel()
        elif request.state == "granted":
            pool = self._pools[request.claim.accelerator_id]
            pool.blocked = True
            pool.revision += 1
            # Grant journal entry already durably pins this incarnation.
        self._dispatch()

    def _dispatch(self) -> None:
        barred: set[str] = set()
        for request in sorted(self._requests.values(), key=lambda r: (r.claim.priority, r.sequence)):
            if request.state != "queued":
                continue
            claim = request.claim
            pool = self._pools[claim.accelerator_id]
            # Once an exclusive is waiting, later shared work cannot extend
            # its drain indefinitely, even with a higher priority.
            if claim.mode == "SHARED" and any(
                r.state == "queued" and r.claim.mode == "EXCLUSIVE"
                and r.claim.accelerator_id == claim.accelerator_id
                and r.sequence < request.sequence for r in self._requests.values()
            ):
                continue
            if claim.accelerator_id in barred:
                continue
            barred.add(claim.accelerator_id)
            if pool.blocked or pool.verifying:
                continue
            active = tuple(pool.active.values())
            profile = next(p for p in pool.policy.profiles if p.profile_id == claim.profile_id)
            if active and (claim.mode == "EXCLUSIVE" or any(g.claim.mode == "EXCLUSIVE" for g in active)):
                continue
            if claim.mode == "SHARED":
                pairs = {frozenset(p) for p in pool.policy.compatible_pairs}
                if (frozenset((claim.profile_id,)) not in pairs
                        or len(active) >= pool.policy.max_shared
                        or any(frozenset((claim.profile_id, g.claim.profile_id)) not in pairs for g in active)):
                    continue
            if sum(g.reserved_bytes for g in active) + profile.reserved_bytes > pool.policy.memory_limit_bytes:
                continue
            try:
                if pool.adapter.can_start(pool.device, claim, active) is not True:
                    pool.blocked = True
                    continue
            except Exception:
                pool.blocked = True
                continue
            pool.generation += 1
            grant = Grant(self._epoch, pool.generation, uuid4().hex,
                          f"accelerator:{pool.device.node_id}:{pool.device.accelerator_id}", claim,
                          profile.reserved_bytes)
            # Pin in memory before persistence: I/O errors cannot lose ownership.
            pool.active[grant.lease_id] = grant
            request.grant, request.state = grant, "granted"
            self._write({"event": "grant", "epoch": grant.epoch,
                         "generation": grant.generation, "lease_id": grant.lease_id,
                         "resource_id": grant.resource_id, "claim": claim.model_dump(mode="json"),
                         "reserved_bytes": grant.reserved_bytes})
            request.future.set_result(grant)
            barred.remove(claim.accelerator_id)

    async def release(self, grant: Grant) -> None:
        self._check()
        pool = self._pools[grant.claim.accelerator_id]
        if pool.active.get(grant.lease_id) != grant:
            raise AdmissionError("stale or forged grant")
        await self._verify(pool, grant)

    async def recover(self, accelerator_id: str) -> None:
        self._check()
        pool = self._pools[accelerator_id]
        if pool.active:
            raise AdmissionError("release pinned owners individually before recovery")
        await self._verify(pool, None)

    async def _verify(self, pool: _Pool, grant: Grant | None) -> None:
        if pool.verifying:
            raise AdmissionError("verification already in progress")
        was_blocked = pool.blocked
        pool.blocked, pool.verifying = True, True
        revision = pool.revision
        try:
            self._journal.seek(0)
            journal = self._journal.read()
            digest = hashlib.sha256(journal).hexdigest()
            challenge = Verification(uuid4().hex, self._epoch, pool.device, digest, journal, grant,
                                     tuple(g for g in pool.active.values() if g != grant))
            if await pool.adapter.verify(challenge) is not True:
                raise AdmissionError("cleanup evidence not verified")
            self._check()
            if revision != pool.revision:
                raise AdmissionError("ownership changed during verification")
            self._write({"event": "release" if grant else "recovery", "epoch": self._epoch,
                         "accelerator_id": pool.device.accelerator_id, "nonce": challenge.nonce,
                         "lease_id": grant.lease_id if grant else None})
            if grant:
                del pool.active[grant.lease_id]
                self._requests[grant.claim.request_id].state = "released"
            # A previously uncertain device requires a separate recovery proof.
            pool.blocked = was_blocked if grant else False
        finally:
            pool.verifying = False
        self._dispatch()

    def snapshot(self) -> dict[str, dict]:
        self._check()
        return {key: {"blocked": p.blocked, "verifying": p.verifying,
                      "generation": p.generation, "active": tuple(p.active.values()),
                      "queued": tuple(r.claim.request_id for r in self._requests.values()
                                      if r.state == "queued" and r.claim.accelerator_id == key)}
                for key, p in self._pools.items()}

    def close(self) -> None:
        """Abandon the DEV instance; durable records remain, restart is blocked."""
        self._check()
        if any(p.verifying for p in self._pools.values()):
            raise AdmissionError("verification in progress")
        for request in self._requests.values():
            if not request.future.done():
                request.future.cancel()
        self._closed = True
        self._journal.close()
