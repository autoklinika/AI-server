"""Fixed injected CPU traces only. REAL_GPU_HANDOFF_NOT_RUN."""
from dataclasses import replace

import pytest

from ai_bridge.gateway.exclusive_handoff_dev import (
    Identity, Inventory, MockRelease, OfflineExclusiveGate,
)

PARENT = Identity("boot-mock", 101, 10, "unit-invocation-mock")
CHILD = Identity("boot-mock", 102, 11, "unit-invocation-mock")
INVENTORY = Inventory((PARENT, CHILD), (PARENT, CHILD), True, True)
RELEASE = MockRelease("attempt-mock", OfflineExclusiveGate.device,
                      PARENT.cgroup_lifetime, "MOCK_TRUSTED_EXTERNAL_RELEASE", True)
TRACE = (("BLOCK_NEW", True), ("QUIESCE", True), ("INVENTORY", INVENTORY),
         ("RELEASE", RELEASE), ("NEXT", True))


def gate():
    return OfflineExclusiveGate(attempt="attempt-mock", members=(PARENT, CHILD))


def replay(g, trace=TRACE):
    for elapsed, (event, evidence) in enumerate(trace):
        g.feed(event, elapsed=elapsed, evidence=evidence)
    return g.state


def assert_latched(g):
    assert g.state == "DIRTY"
    assert replay(g) == "DIRTY"
    assert g.gpu_reuse_safe == "NOT_VERIFIED"


def test_successful_cpu_mock_sequence():
    g = gate()
    for elapsed, (event, evidence) in enumerate(TRACE):
        result = g.feed(event, elapsed=elapsed, evidence=evidence)
        assert result == ("CPU_MOCK_NEXT_ALLOWED" if event == "NEXT" else event + "_ACK")
    assert g.gpu_reuse_safe == "NOT_VERIFIED"


@pytest.mark.parametrize("inventory", [
    replace(INVENTORY, members=(PARENT,)),  # missing child
    replace(INVENTORY, gpu_owners=(replace(CHILD, pid=999),)),  # unknown owner
    replace(INVENTORY, members=(PARENT, replace(CHILD, cgroup_lifetime="other"))),
    replace(INVENTORY, members=(PARENT, replace(CHILD, birth=99))),  # PID reuse
    replace(INVENTORY, members=(PARENT, replace(CHILD, boot=[]))),
    replace(INVENTORY, gpu_owners=None),
    replace(INVENTORY, complete=False),
    replace(INVENTORY, device_access_fenced=False),
    replace(INVENTORY, members=(PARENT, PARENT)),
    None,
])
def test_inventory_rejection_is_terminal(inventory):
    g = gate()
    replay(g, TRACE[:2] + (("INVENTORY", inventory),) + TRACE[3:])
    assert_latched(g)


@pytest.mark.parametrize("release", [
    replace(RELEASE, approved=False),
    replace(RELEASE, approved=1),
    replace(RELEASE, source="KFD_FUSER_POINT_IN_TIME"),
    replace(RELEASE, attempt="stale"),
    replace(RELEASE, cgroup_lifetime="restarted"),
    replace(RELEASE, device="rocm:physical"),
    None,
])
def test_release_rejection_is_terminal(release):
    g = gate()
    replay(g, TRACE[:3] + (("RELEASE", release),) + TRACE[4:])
    assert_latched(g)


@pytest.mark.parametrize("elapsed", [5, 6, -1, float("nan"), float("inf")])
def test_timeout_or_invalid_clock(elapsed):
    g = gate()
    replay(g, TRACE[:2])
    g.feed("INVENTORY", elapsed=elapsed, evidence=INVENTORY)
    assert_latched(g)


def test_clock_regression():
    g = gate()
    replay(g, TRACE[:2])
    g.feed("INVENTORY", elapsed=0, evidence=INVENTORY)
    assert_latched(g)


@pytest.mark.parametrize("event", ["QUIESCE", "RELEASE", "NEXT", "unknown"])
def test_out_of_order_or_denied_early_start(event):
    g = gate()
    g.feed(event, elapsed=0, evidence=True)
    assert_latched(g)


@pytest.mark.parametrize("step", [0, 1, 4])
def test_denied_acknowledgement_or_start(step):
    g = gate()
    trace = TRACE[:step] + ((TRACE[step][0], False),) + TRACE[step + 1:]
    replay(g, trace)
    assert_latched(g)


def test_double_release():
    g = gate()
    replay(g, TRACE[:4])
    g.feed("RELEASE", elapsed=4, evidence=RELEASE)
    assert_latched(g)


def test_cannot_reuse_completed_attempt():
    g = gate()
    replay(g)
    g.feed("NEXT", elapsed=4, evidence=True)
    assert_latched(g)


@pytest.mark.parametrize("timeout", [0, 11, float("nan"), True])
def test_bounded_configuration(timeout):
    with pytest.raises(ValueError):
        OfflineExclusiveGate(attempt="mock", members=(PARENT, CHILD), timeout=timeout)
