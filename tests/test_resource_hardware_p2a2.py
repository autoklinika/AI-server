"""P2-A2 CPU/mock checks for bounded Linux observation and RM isolation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.resource_hardware import (
    HardwareReading,
    collect_linux_hardware,
    observe_hardware_source,
    parse_meminfo,
    parse_nvidia_csv,
    public_hardware_summary,
    read_amd_drm,
)
from ai_bridge.settings import Settings

GIB = 1024**3
NVIDIA_A = "GPU-11111111-2222-3333-4444-555555555555"
NVIDIA_B = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NVIDIA_ROW = f"0, {NVIDIA_A}, 00000000:03:00.0, 16311, 512"
SECOND_ROW = f"1, {NVIDIA_B}, 00000000:04:00.0, 49140, 2048"
BOOT = "01234567-89ab-cdef-0123-456789abcdef"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _hardware_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    drm = tmp_path / "drm"
    drm.mkdir()
    gpu = tmp_path / "pci" / "0000:c4:00.0"
    gpu.mkdir(parents=True)
    (gpu / "vendor").write_text("0x1002\n")
    (gpu / "mem_info_vram_total").write_text(str(96 * GIB))
    (gpu / "mem_info_vram_used").write_text(str(256 * 1024**2))
    (drm / "card0").mkdir()
    (drm / "card0" / "device").symlink_to(gpu, target_is_directory=True)

    # Real /sys/class/drm also includes card0-DP-1 etc. Never parse these
    # connector entries as GPU devices.
    (drm / "card0-DP-1").mkdir()
    other = tmp_path / "pci" / "0000:03:00.0"
    other.mkdir()
    (other / "vendor").write_text("0x10de\n")
    (drm / "card1").mkdir()
    (drm / "card1" / "device").symlink_to(other, target_is_directory=True)

    mem = tmp_path / "meminfo"
    # Deliberately different from 96GiB AMD driver VRAM, as observed in DEV.
    mem.write_text("MemTotal:       31965700 kB\nMemAvailable:   28000000 kB\n")
    boot = tmp_path / "boot_id"
    boot.write_text(BOOT + "\n")
    return drm, mem, boot, gpu


def _collect(
    tmp_path: Path,
    *,
    nvidia: str = NVIDIA_ROW,
    expect_nvidia: int = 1,
    expect_amd: int = 1,
    expected_uuids: tuple[str, ...] = (),
) -> HardwareReading:
    drm, mem, boot, _ = _hardware_files(tmp_path)
    return collect_linux_hardware(
        nvidia_query=lambda: nvidia,
        drm_root=drm,
        proc_meminfo=mem,
        proc_boot_id=boot,
        expected_nvidia=expect_nvidia,
        expected_amd=expect_amd,
        expected_nvidia_uuids=expected_uuids,
        now_ns=lambda: 12345,
    )


def _gateway(tmp_path: Path, *, enabled: bool = False, hardware_source=None):
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []}, request=request)

    return create_gateway_app(
        Settings(
            _env_file=None,
            gateway_resource_hardware_observation_enabled=enabled,
            gateway_gpu_marker=tmp_path / "rm-gpu-marker.blocked",
            gateway_max_concurrency=1,
        ),
        upstream_transport=httpx.MockTransport(upstream),
        resource_hardware_source=hardware_source,
    )


def test_nvidia_csv_converts_mib_exactly_and_normalizes_pci():
    (reading,) = parse_nvidia_csv(NVIDIA_ROW)
    assert reading.vendor == "nvidia"
    assert reading.identity == NVIDIA_A
    assert reading.identity_source == "driver_uuid"
    assert reading.pci_bdf == "0000:03:00.0"
    assert reading.memory_scope == "dedicated_vram"
    assert reading.total_bytes == 16311 * 1024**2
    assert reading.used_bytes == 512 * 1024**2


def test_two_different_cards_are_sorted_by_uuid_not_volatile_index():
    a = parse_nvidia_csv(NVIDIA_ROW + "\n" + SECOND_ROW)
    b = parse_nvidia_csv(
        f"8, {NVIDIA_B}, 00000000:04:00.0, 49140, 2048\n"
        f"4, {NVIDIA_A}, 00000000:03:00.0, 16311, 512"
    )
    assert a == b
    assert {item.total_bytes for item in a} == {16311 * 1024**2, 49140 * 1024**2}


@pytest.mark.parametrize(
    "input_csv",
    [
        "0, N/A, 00000000:03:00.0, 16311, 1",
        "0, GPU-invalid, 00000000:03:00.0, 16311, 1",
        f"0, {NVIDIA_A}, invalid, 16311, 1",
        f"0, {NVIDIA_A}, 00000000:03:00.0, 0, 1",
        f"0, {NVIDIA_A}, 00000000:03:00.0, 16311, 16312",
        f"0, {NVIDIA_A}, 00000000:03:00.0, N/A, 0",
        f"0, {NVIDIA_A}, 00000000:03:00.0, 16311",
        f"0, {NVIDIA_A}, 00000000:03:00.0, 16311, -1",
        f"0, {NVIDIA_A}, 12340000:03:00.0, 16311, 1",
        NVIDIA_ROW + "\n" + NVIDIA_ROW,
        NVIDIA_ROW + "\n" + f"1, {NVIDIA_B}, 00000000:03:00.0, 100, 1",
        NVIDIA_ROW + "\n" + f"0, {NVIDIA_B}, 00000000:04:00.0, 100, 1",
        "X" * (16 * 1024 + 1),
    ],
)
def test_bad_nvidia_telemetry_is_rejected(input_csv):
    with pytest.raises(ValueError):
        parse_nvidia_csv(input_csv)


def test_amd_sysfs_ignores_connectors_and_never_infers_uma(tmp_path):
    drm, _, _, _ = _hardware_files(tmp_path)
    readings = read_amd_drm(drm)
    assert len(readings) == 1
    (amd,) = readings
    assert amd.vendor == "amd"
    assert amd.identity_source == "boot_pci"
    assert amd.pci_bdf == "0000:c4:00.0"
    assert amd.memory_scope == "amd_driver_vram_unclassified"
    assert amd.total_bytes == 96 * GIB
    assert amd.used_bytes == 256 * 1024**2


def test_unreadable_or_invalid_amd_counters_do_not_imply_free_memory(tmp_path):
    drm, _, _, gpu = _hardware_files(tmp_path)
    (gpu / "mem_info_vram_used").unlink()
    reading = read_amd_drm(drm)[0]
    assert reading.total_bytes is None
    assert reading.used_bytes is None

    (gpu / "mem_info_vram_used").write_text(str(97 * GIB))
    reading = read_amd_drm(drm)[0]
    assert reading.total_bytes is None

    (gpu / "mem_info_vram_used").write_text("not a counter")
    assert read_amd_drm(drm)[0].used_bytes is None


def test_duplicate_amd_device_alias_is_rejected(tmp_path):
    drm, _, _, gpu = _hardware_files(tmp_path)
    (drm / "card2").mkdir()
    (drm / "card2" / "device").symlink_to(gpu, target_is_directory=True)
    with pytest.raises(ValueError, match="duplicate AMD"):
        read_amd_drm(drm)


@pytest.mark.parametrize(
    "raw",
    [
        "MemTotal: 1024 kB\nMemAvailable: 1025 kB\n",
        "MemTotal: 1024 MB\nMemAvailable: 100 kB\n",
        "MemTotal: 1024 kB\n",
        "MemTotal: 1024 kB\nMemTotal: 1024 kB\nMemAvailable: 100 kB\n",
        "",
    ],
)
def test_bad_host_meminfo_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_meminfo(raw)


def test_amd_driver_vram_and_host_ram_are_separate_unverified_apertures(tmp_path):
    sample = _collect(tmp_path)
    assert sample.issues == ()
    assert sample.boot_id == BOOT
    assert sample.observed_at_ns == 12345
    assert len(sample.devices) == 2
    assert not sample.authorizes_execution

    summary = public_hardware_summary(sample, rm_lease_count=0)
    assert summary["result"] == "PARTIAL"
    assert "amd_memory_relation_unverified" in summary["reason_codes"]
    assert (
        summary["memory_observations"]["amd_driver_reported_unclassified"][0][
            "total_bytes"
        ]
        == 96 * GIB
    )
    assert summary["memory_observations"]["host_ram"]["total_bytes"] == 31965700 * 1024
    assert summary["memory_domain_mapping"] == "unverified"
    assert summary["allocation_attribution"] == "unverified"
    assert summary["authorizes_execution"] is False

    # AMD reports a 96GiB VRAM aperture while Linux exposes roughly 30GiB
    # host RAM. Neither figure is license to sum or allocate that memory.
    assert sample.host.total_bytes != sample.devices[0].total_bytes


def test_expected_gpu_loss_is_detected_even_if_others_remain(tmp_path):
    sample = _collect(tmp_path, expect_nvidia=2)
    assert "nvidia_count_mismatch" in sample.issues
    public = public_hardware_summary(sample, rm_lease_count=0)
    assert public["result"] == "PARTIAL"
    assert public["counts"] == {"nvidia": 1, "amd": 1}
    assert public["authorizes_execution"] is False


def test_hotplug_replacement_with_same_count_is_rejected_by_expected_uuid(tmp_path):
    sample = _collect(tmp_path, expected_uuids=(NVIDIA_B,))
    assert "nvidia_identity_mismatch" in sample.issues
    assert "nvidia_count_mismatch" not in sample.issues


def test_failed_nvidia_probe_retains_other_observation(tmp_path):
    drm, mem, boot, _ = _hardware_files(tmp_path)

    def failure():
        raise OSError("device does not exist")

    sample = collect_linux_hardware(
        nvidia_query=failure,
        drm_root=drm,
        proc_meminfo=mem,
        proc_boot_id=boot,
        expected_nvidia=1,
        expected_amd=1,
    )
    assert "nvidia_observation_unavailable" in sample.issues
    assert "nvidia_count_mismatch" in sample.issues
    assert len(sample.devices) == 1 and sample.devices[0].vendor == "amd"
    assert not sample.authorizes_execution


def test_corrupt_sysfs_does_not_turn_unknown_into_healthy_gpu(tmp_path):
    drm, mem, boot, gpu = _hardware_files(tmp_path)
    (gpu / "vendor").write_text("0x1002\n")
    (drm / "card2").mkdir()
    (drm / "card2" / "device").symlink_to(gpu, target_is_directory=True)

    sample = collect_linux_hardware(
        nvidia_query=lambda: NVIDIA_ROW,
        drm_root=drm,
        proc_meminfo=mem,
        proc_boot_id=boot,
        expected_amd=1,
    )
    assert "amd_observation_unavailable" in sample.issues
    assert "amd_count_mismatch" in sample.issues
    assert any(d.vendor == "nvidia" for d in sample.devices)


def test_missing_boot_id_marks_snapshot_incomplete(tmp_path):
    drm, mem, boot, _ = _hardware_files(tmp_path)
    boot.unlink()
    sample = collect_linux_hardware(
        nvidia_query=lambda: NVIDIA_ROW,
        drm_root=drm,
        proc_meminfo=mem,
        proc_boot_id=boot,
    )
    assert sample.boot_id is None
    assert "boot_epoch_unavailable" in sample.issues
    assert public_hardware_summary(sample, rm_lease_count=0)["result"] == "PARTIAL"


def test_sanitized_summary_does_not_expose_private_uuids_or_bdf(tmp_path):
    sample = _collect(tmp_path)
    summary = public_hardware_summary(sample, rm_lease_count=3)
    output = json.dumps(summary)
    for forbidden in (NVIDIA_A, "gpu-amd", "0000:c4:00.0", BOOT, "nvidia-smi"):
        assert forbidden not in output
    assert summary["rm_lease_count"] == 3
    assert summary["allocation_attribution"] == "unverified"


def test_missing_source_returns_unknown_without_risky_auto_discovery():
    value = observe_hardware_source(None, rm_lease_count=0)
    assert value["result"] == "UNKNOWN"
    assert value["reason_codes"] == ["missing_hardware_observation"]
    assert value["authorizes_execution"] is False


def test_supplier_error_is_generic_and_cannot_leak_exception():
    def faulty():
        raise RuntimeError("private-secret-to-hide")

    result = observe_hardware_source(faulty, rm_lease_count=4)
    assert result["result"] == "UNKNOWN"
    assert result["reason_codes"] == ["hardware_source_error"]
    assert "private-secret" not in json.dumps(result)


def test_no_devices_never_produces_safe_inventory(tmp_path):
    drm, mem, boot, gpu = _hardware_files(tmp_path)
    (gpu / "vendor").write_text("0x10de\n")
    result = collect_linux_hardware(
        nvidia_query=lambda: "",
        drm_root=drm,
        proc_meminfo=mem,
        proc_boot_id=boot,
        expected_nvidia=1,
        expected_amd=1,
    )
    assert result.devices == ()
    assert public_hardware_summary(result, rm_lease_count=0)["result"] == "PARTIAL"
    assert "no_gpu_observed" in public_hardware_summary(result)["reason_codes"]


@pytest.mark.parametrize("count", [-1, 33, 1.0, True, "1"])
def test_expected_device_count_is_strict(tmp_path, count):
    drm, mem, boot, _ = _hardware_files(tmp_path)
    with pytest.raises(ValueError):
        collect_linux_hardware(
            nvidia_query=lambda: NVIDIA_ROW,
            drm_root=drm,
            proc_meminfo=mem,
            proc_boot_id=boot,
            expected_nvidia=count,
        )


@pytest.mark.anyio
async def test_gateway_default_off_does_not_read_hardware_or_change_status(tmp_path):
    called = []

    def forbidden():
        called.append(1)
        raise AssertionError("Hardware read forbidden without opt-in")

    app = _gateway(tmp_path, hardware_source=forbidden)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            status = (await client.get("/status")).json()
            assert "resource_hardware" not in status
            assert "resource_shadow" not in status
            assert "resource_hardware" not in (await client.get("/health")).json()
            assert status["active_count"] == 0
            assert not called


@pytest.mark.anyio
async def test_gateway_enabled_without_source_is_unknown_not_a_gpu_grant(tmp_path):
    app = _gateway(tmp_path, enabled=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = (await client.get("/status")).json()
            assert result["resource_hardware"]["result"] == "UNKNOWN"
            assert result["resource_hardware"]["authorizes_execution"] is False
            assert result["resource_leases"]["lease_count"] == 0
            assert "resource_hardware" not in (await client.get("/health")).json()


@pytest.mark.anyio
async def test_gateway_enabled_uses_precollected_sample_but_not_lease_authority(
    tmp_path,
):
    sample = _collect(tmp_path)
    app = _gateway(tmp_path, enabled=True, hardware_source=lambda: sample)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            initial = (await client.get("/status")).json()
            assert initial["resource_hardware"]["counts"] == {"nvidia": 1, "amd": 1}
            assert (
                initial["resource_hardware"]["allocation_attribution"] == "unverified"
            )
            lease = await client.post(
                "/resource/leases",
                json={"source": "hardware-read-only", "priority": 50},
            )
            assert lease.status_code == 201
            active = (await client.get("/status")).json()
            assert active["resource_hardware"]["rm_lease_count"] == 1
            assert active["resource_hardware"]["authorizes_execution"] is False
            assert active["active_count"] == 1
            await client.delete(f"/resource/leases/{lease.json()['lease_id']}")
            finished = (await client.get("/status")).json()
            assert finished["resource_hardware"]["rm_lease_count"] == 0
            assert finished["active_count"] == 0
            assert "resource_hardware" not in (await client.get("/health")).json()


@pytest.mark.anyio
async def test_repeated_status_reads_dont_alter_existing_rm(tmp_path):
    sample = _collect(tmp_path)
    app = _gateway(tmp_path, enabled=True, hardware_source=lambda: sample)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            baseline = (await client.get("/status")).json()
            many = await asyncio.gather(*(client.get("/status") for _ in range(9)))
            assert all(r.status_code == 200 for r in many)
            current = (await client.get("/status")).json()
            for key in (
                "active_count",
                "queued_count",
                "gpu_residency",
                "resource_manager",
            ):
                assert current[key] == baseline[key]


def test_explicit_collector_does_not_invoke_external_tools_when_injected(
    tmp_path, monkeypatch
):
    import socket
    import subprocess

    drm, mem, boot, _ = _hardware_files(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("external action forbidden in injected observer test")

    with monkeypatch.context() as guard:
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(subprocess, "run", forbidden)
        result = collect_linux_hardware(
            nvidia_query=lambda: NVIDIA_ROW,
            drm_root=drm,
            proc_meminfo=mem,
            proc_boot_id=boot,
            now_ns=lambda: 13,
        )
    assert result.observed_at_ns == 13
    assert len(result.devices) == 2
