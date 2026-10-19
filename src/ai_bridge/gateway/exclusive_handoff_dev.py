"""Offline CPU acceptance model only; no I/O, real grants or launch hooks.

Injected assertions are NOT authenticated physical evidence. This is neither a
SafetyAdapter nor a coordinator. Never wire its result into GPU admission.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Identity:
    boot: str
    pid: int
    birth: int
    cgroup_lifetime: str


def _valid_identity(p):
    return (isinstance(p, Identity) and type(p.boot) is str and bool(p.boot)
            and type(p.pid) is int and p.pid > 1
            and type(p.birth) is int and p.birth > 0
            and type(p.cgroup_lifetime) is str and bool(p.cgroup_lifetime))


@dataclass(frozen=True)
class Inventory:
    members: tuple[Identity, ...]
    gpu_owners: tuple[Identity, ...]
    complete: bool
    device_access_fenced: bool


@dataclass(frozen=True)
class MockRelease:
    attempt: str
    device: str
    cgroup_lifetime: str
    source: str
    approved: bool


class OfflineExclusiveGate:
    """Single-use, bounded simulated trace; DIRTY is terminal, including after NEXT.

    Time is injected elapsed seconds, starting at zero. Callers must submit a
    deadline tick if the trace stalls. No wall-clock monitoring is performed.
    The only accepted resource is a fixed virtual CPU device.
    """
    device = "cpu:virtual:handoff-test"
    gpu_reuse_safe = "NOT_VERIFIED"
    _events = ("BLOCK_NEW", "QUIESCE", "INVENTORY", "RELEASE", "NEXT")

    def __init__(self, *, attempt: str, members: tuple[Identity, ...],
                 timeout: float = 5):
        if (type(timeout) not in (int, float) or not isfinite(timeout)
                or not 0 < timeout <= 10):
            raise ValueError("bounded CPU deadline required")
        if (type(attempt) is not str or not attempt
                or type(members) is not tuple or not members or len(members) > 128
                or any(not _valid_identity(p) for p in members)
                or len({p.pid for p in members}) != len(members)
                or len({(p.boot, p.cgroup_lifetime) for p in members}) != 1):
            raise ValueError("complete owned incarnation manifest required")
        self._attempt, self._members = attempt, frozenset(members)
        self._lifetime = members[0].cgroup_lifetime
        self._timeout, self._last, self._step = timeout, 0, 0
        self._state = "BLOCKED"

    @property
    def state(self):
        return self._state

    def feed(self, event: str, *, elapsed: float, evidence=None) -> str:
        if self._state == "DIRTY":
            return self._state
        if (type(elapsed) not in (int, float) or not isfinite(elapsed)
                or elapsed < self._last or elapsed >= self._timeout
                or self._step >= len(self._events)
                or event != self._events[self._step]):
            self._state = "DIRTY"
            return self._state
        self._last = elapsed
        if event in ("BLOCK_NEW", "QUIESCE", "NEXT"):
            valid = evidence is True  # explicit acknowledgement, including start
        elif event == "INVENTORY":
            valid = (isinstance(evidence, Inventory)
                     and evidence.complete is True
                     and evidence.device_access_fenced is True
                     and type(evidence.members) is tuple
                     and len(evidence.members) == len(self._members)
                     and all(_valid_identity(p) for p in evidence.members)
                     and frozenset(evidence.members) == self._members
                     and type(evidence.gpu_owners) is tuple
                     and len(evidence.gpu_owners) <= len(self._members)
                     and all(_valid_identity(p) and p in self._members
                             for p in evidence.gpu_owners)
                     and len(set(evidence.gpu_owners)) == len(evidence.gpu_owners))
        else:
            # Point-in-time KFD/fuser is expressly NOT an E_safe source.
            valid = (isinstance(evidence, MockRelease)
                     and evidence.approved is True
                     and evidence.source == "MOCK_TRUSTED_EXTERNAL_RELEASE"
                     and evidence.attempt == self._attempt
                     and evidence.device == self.device
                     and evidence.cgroup_lifetime == self._lifetime)
        if not valid:
            self._state = "DIRTY"
        else:
            self._step += 1
            self._state = ("CPU_MOCK_NEXT_ALLOWED" if event == "NEXT"
                           else event + "_ACK")
        return self._state
