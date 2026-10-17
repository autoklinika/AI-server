"""CPU-only fixtures: every proc/sys/device metadata read is injected."""
import asyncio
from dataclasses import replace

import pytest

from ai_bridge.gateway.accelerator_admission import AdmissionError, SafetyAdapter, Verification
from ai_bridge.gateway.accelerator_evidence import (
    EvidenceCollector, NonApprovingSafetyAdapter, birth_ticks,
)
from test_accelerator_admission_n1 import claim, configuration, core, SyntheticAdapter

BOOT = "12345678-1234-1234-1234-123456789abc"
OTHER_BOOT = "22345678-1234-1234-1234-123456789abc"
BOOT_PATH = "/proc/sys/kernel/random/boot_id"


def proc_stat(ticks=42):
    return "123 (worker (a) b)\nname)) S " + "0 " * 18 + str(ticks) + " 0 0"


class FakeReader:
    def __init__(self):
        self.texts = {BOOT_PATH: BOOT, "/proc/123/stat": proc_stat(),
                      "/proc/123/status": "Name:\tworker\nUid:\t1001\t1001\t1001\t1001\n",
                      "/proc/123/cgroup": "0::/workers/a\n"}
        self.links = {}
        self.dirs = {"/proc/123/fd": ("3",)}
        self.numbers = {"/proc/123/fd/3": (226, 128)}

    def get(self, values, path):
        if path not in values:
            raise FileNotFoundError(path)
        value = values[path]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def text(self, path):
        return self.get(self.texts, path)

    def realpath(self, path):
        return self.get(self.links, path)

    def names(self, path):
        return self.get(self.dirs, path)

    def device_number(self, path):
        return self.get(self.numbers, path)

    def gpu(self, index, vendor="0x1002"):
        pci = f"/sys/devices/pci0000:00/0000:00:01.0/0000:0{index+1}:00.0"
        node = pci + f"/drm/renderD{128+index}"
        alias = f"/sys/class/drm/renderD{128+index}"
        for path in (alias, node, f"/mock/alias{index}"):
            self.links[path] = node
            self.links[path + "/device"] = pci
        self.links[pci + "/subsystem"] = "/sys/bus/pci"
        self.links["/sys/bus/pci/devices/" + pci.rsplit("/", 1)[-1]] = pci
        self.links[f"/sys/dev/char/226:{128+index}"] = node
        self.texts[pci + "/vendor"] = vendor
        self.texts[pci + "/device"] = "0x1234"
        return alias, pci


@pytest.fixture
def fixture():
    reader = FakeReader()
    reader.gpu(0)
    reader.gpu(1, "0x8086")
    return reader, EvidenceCollector(reader)


def test_two_cards_aliases_and_boot_scoped_identity(fixture):
    _, collector = fixture
    result = collector.devices({"amd": ("/sys/class/drm/renderD128", "/mock/alias0"),
                                "intel": ("/sys/class/drm/renderD129",)})
    assert result.status == "OBSERVED"
    a, b = (v for _, v in result.value)
    assert a.bdf != b.bdf and a.boot_id == b.boot_id == BOOT
    assert a.vendor == "0x1002" and b.vendor == "0x8086"
    assert collector.devices({"a": ("/mock/alias0",), "b": ("/sys/class/drm/renderD128",)}).status == "UNKNOWN"
    assert collector.devices({"a": ("/mock/alias0", "/mock/alias1")}).status == "UNKNOWN"


@pytest.mark.parametrize("mutation", ["missing", "non-pci", "bad-bdf", "subsystem", "bus-alias", "vendor", "device", "boot", "empty"])
def test_invalid_identity(fixture, mutation):
    reader, collector = fixture
    alias, pci = reader.gpu(0)
    bindings = {"a": (alias,)}
    if mutation == "missing":
        del reader.links[alias + "/device"]
    elif mutation in {"non-pci", "bad-bdf"}:
        reader.links[alias + "/device"] = "/sys/devices/platform/gpu" if mutation == "non-pci" else pci.replace("01:00.0", "01:ff.9")
    elif mutation == "subsystem":
        reader.links[pci + "/subsystem"] = "/sys/bus/platform"
    elif mutation == "bus-alias":
        reader.links["/sys/bus/pci/devices/0000:01:00.0"] = "/sys/devices/other"
    elif mutation in {"vendor", "device"}:
        reader.texts[pci + "/" + mutation] = "garbage"
    elif mutation == "boot":
        reader.texts[BOOT_PATH] = [BOOT, OTHER_BOOT]
    else:
        bindings = {"a": ()}
    result = collector.devices(bindings)
    assert result.status == "UNKNOWN" and result.value is None


def test_nvidia_drm(fixture):
    reader, collector = fixture
    reader.gpu(0, "0x10de")
    assert collector.devices({"nvidia": ("/mock/alias0",)}).value[0][1].vendor == "0x10de"


@pytest.mark.parametrize("raw", ["", "123 (x) S 1", proc_stat().replace("123 (", "124 ("), proc_stat(0), proc_stat(-1)])
def test_malformed_stat(raw):
    with pytest.raises(ValueError):
        birth_ticks(raw, 123)


def test_process_identity_and_handles(fixture):
    _, collector = fixture
    assert birth_ticks(proc_stat(), 123) == 42
    result = collector.process(123, epoch="epoch-a")
    assert result.status == "OBSERVED"
    snapshot = result.value
    assert snapshot.birth_ticks == 42 and snapshot.uids == (1001,) * 4
    assert snapshot.cgroups == (("0", "", "/workers/a"),)
    assert snapshot.handles[0].identity.value.bdf == "0000:01:00.0"
    assert snapshot.matches(snapshot)
    for changes in ({"epoch": "old"}, {"boot_id": OTHER_BOOT}, {"birth_ticks": 43},
                    {"cgroups": (("0", "", "/workers/b"),)}, {"uids": (1002,) * 4}):
        assert not snapshot.matches(replace(snapshot, **changes))


@pytest.mark.parametrize("path,new", [
    ("/proc/123/stat", proc_stat(43)),
    ("/proc/123/stat", FileNotFoundError("exit race")),
    ("/proc/123/cgroup", "0::/workers/b"),
    ("/proc/123/status", "Uid: 1002 1002 1002 1002"),
    (BOOT_PATH, OTHER_BOOT),
])
def test_observation_races_are_unknown(fixture, path, new):
    reader, collector = fixture
    reader.texts[path] = [reader.texts[path], new]
    result = collector.process(123, epoch="e")
    assert result.status == "UNKNOWN" and result.value is None


@pytest.mark.parametrize("where", ["status", "fd-list", "fd-stat", "sysfs"])
def test_cross_uid_permission_denied_is_not_empty(fixture, where):
    reader, collector = fixture
    error = PermissionError(1, "EPERM cross-UID")
    if where == "status":
        reader.texts["/proc/123/status"] = error
    elif where == "fd-list":
        reader.dirs["/proc/123/fd"] = error
    elif where == "fd-stat":
        reader.numbers["/proc/123/fd/3"] = error
    else:
        reader.links["/sys/dev/char/226:128"] = error
    result = collector.process(123, epoch="e")
    assert result.status == "UNKNOWN" and result.value is None


@pytest.mark.parametrize("kfd_path", ["/sys/devices/virtual/misc/kfd", "/sys/devices/virtual/kfd/kfd"])
def test_kfd_global_ambiguity_and_other_char_devices(fixture, kfd_path):
    reader, collector = fixture
    reader.dirs["/proc/123/fd"] = ("3", "4", "5")
    reader.numbers.update({"/proc/123/fd/4": (235, 0), "/proc/123/fd/5": (195, 0)})
    reader.links.update({"/sys/dev/char/235:0": kfd_path,
                         "/sys/dev/char/195:0": "/sys/devices/virtual/nvidia/nvidia0"})
    handles = collector.process(123, epoch="e").value.handles
    assert [h.kind for h in handles] == ["DRM", "KFD", "OTHER"]
    assert all(h.identity.status == "UNKNOWN" and h.identity.value is None for h in handles[1:])


def test_fd_change_and_exit_are_unknown(fixture):
    reader, collector = fixture
    reader.dirs["/proc/123/fd"] = [("3",), ()]
    assert collector.process(123, epoch="e").status == "UNKNOWN"
    reader.dirs["/proc/123/fd"] = ("3",)
    reader.numbers["/proc/123/fd/3"] = FileNotFoundError("closed during scan")
    assert collector.process(123, epoch="e").status == "UNKNOWN"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_adapter_never_approves_even_empty_or_unrelated_owners(fixture):
    _, collector = fixture
    observed = collector.process(123, epoch="e")  # visible unrelated GPU owner
    assert observed.value.handles
    device = configuration()[0].accelerators[0]
    for backend in ("cpu", "rocm", "cuda", "vulkan", "unknown"):
        adapter: SafetyAdapter = NonApprovingSafetyAdapter(backend)
        assert adapter.can_start(device, claim("a"), ()) is False
        for epoch in ("e", "stale"):
            assert await adapter.verify(Verification("nonce", epoch, device, "digest", b"", None, ())) is False


@pytest.mark.anyio
async def test_n3_recovery_never_unblocks_or_falls_back(tmp_path):
    adapter = NonApprovingSafetyAdapter("cpu")
    registry, policies = configuration()
    policies = tuple(p.model_copy(update={"adapter_id": adapter.adapter_id}) for p in policies)
    rm = core(tmp_path, adapter, config=(registry, policies))
    try:
        rm.submit(claim("a"))
        results = await asyncio.gather(rm.recover("gpu-0"), rm.recover("gpu-0"), return_exceptions=True)
        assert all(isinstance(r, AdmissionError) for r in results)
        state = rm.snapshot()["gpu-0"]
        assert state["blocked"] and state["active"] == () and state["queued"] == ("a",)
    finally:
        rm.close()


@pytest.mark.anyio
async def test_n3_release_and_recovery_preserve_pinned_owner(tmp_path):
    # Test-only setup seeds an existing owner through N1's synthetic adapter.
    # Production N3 has no success mode; replacement models verifier takeover.
    synthetic = SyntheticAdapter()
    rm = core(tmp_path, synthetic)
    try:
        await rm.recover("gpu-0")
        rm.submit(claim("a"))
        grant = await rm.wait("a")
        rm._pools["gpu-0"].adapter = NonApprovingSafetyAdapter("cpu")
        results = await asyncio.gather(rm.release(grant), rm.recover("gpu-0"), return_exceptions=True)
        assert all(isinstance(r, AdmissionError) for r in results)
        assert rm.snapshot()["gpu-0"]["active"] == (grant,)
        assert rm.snapshot()["gpu-0"]["blocked"]
    finally:
        rm.close()


def test_sibling_pci_functions_are_not_independent_cards(fixture):
    reader, collector = fixture
    alias, pci = reader.gpu(1)
    new = pci.replace("0000:02:00.0", "0000:01:00.1")
    for key, value in list(reader.links.items()):
        if isinstance(value, str) and pci in value:
            reader.links[key.replace(pci, new)] = value.replace(pci, new)
    reader.links[new + "/subsystem"] = "/sys/bus/pci"
    reader.links["/sys/bus/pci/devices/0000:01:00.1"] = new
    reader.texts[new + "/vendor"] = "0x1002"
    reader.texts[new + "/device"] = "0x1234"
    result = collector.devices({"a": ("/mock/alias0",), "b": (alias,)})
    assert result.status == "UNKNOWN" and "sibling" in result.reason


@pytest.mark.parametrize("field,value", [
    ("status", "Name: worker"), ("status", "Uid: 1 2 3"),
    ("cgroup", ""), ("cgroup", "0::relative"),
    ("cgroup", "0::/a\n0::/b"), ("stat", "123 malformed"),
])
def test_missing_or_malformed_process_metadata(fixture, field, value):
    reader, collector = fixture
    reader.texts["/proc/123/" + field] = value
    assert collector.process(123, epoch="e").status == "UNKNOWN"


def test_empty_observed_fd_table_does_not_approve(fixture):
    reader, collector = fixture
    reader.dirs["/proc/123/fd"] = ()
    assert collector.process(123, epoch="e").value.handles == ()
    assert NonApprovingSafetyAdapter("rocm").can_start(configuration()[0].accelerators[0], claim("a"), ()) is False


@pytest.mark.anyio
async def test_unrelated_active_grant_and_stale_challenges_are_denied():
    from ai_bridge.gateway.accelerator_admission import Grant
    device = configuration()[0].accelerators[0]
    owner = Grant("old-epoch", 1, "lease", "resource", claim("unrelated"), 40)
    adapter = NonApprovingSafetyAdapter("cpu")
    assert adapter.can_start(device, claim("new"), (owner,)) is False
    for grant, remaining in ((None, (owner,)), (owner, ())):
        assert await adapter.verify(Verification("n", "new-epoch", device, "bad-digest", b"", grant, remaining)) is False


def test_sysfs_identity_change_during_collection_is_unknown(fixture):
    reader, collector = fixture
    _, pci = reader.gpu(0)
    reader.texts[pci + "/device"] = ["0x1234", "0x5678"]
    assert collector.devices({"a": ("/mock/alias0",)}).status == "UNKNOWN"
