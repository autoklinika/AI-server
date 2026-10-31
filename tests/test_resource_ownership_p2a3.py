"""CPU/mock P2-A3: process fingerprints, lease candidates and AMD aperture safety."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.gateway.resource_gpu_process import (
    ComputeProcess,
    ProcessObservation,
    collect_compute_processes,
    parse_compute_csv,
    parse_proc_start_ticks,
)
from ai_bridge.gateway.resource_hardware import (
    GpuReading,
    HardwareReading,
    HostReading,
)
from ai_bridge.gateway.resource_memory_domains import (
    collect_amd_apertures,
    summarize_memory_relation,
)
from ai_bridge.gateway.resource_ownership import (
    ProcessLeaseClaim,
    observe_ownership_sources,
    summarize_ownership,
)
from ai_bridge.settings import Settings

GIB = 1024**3
BOOT = "01234567-89ab-cdef-0123-456789abcdef"
GPU_A = "GPU-11111111-2222-3333-4444-555555555555"
GPU_B = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PID = 4321
BIRTH = 98425


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _hardware(*, now: int = 1000, two_rtx: bool = False) -> HardwareReading:
    gpu = (
        GpuReading(
            vendor="nvidia",
            identity=GPU_A,
            identity_source="driver_uuid",
            pci_bdf="0000:03:00.0",
            memory_scope="dedicated_vram",
            total_bytes=16 * GIB,
            used_bytes=GIB,
        ),
        GpuReading(
            vendor="amd",
            identity="boot-pci:0000:c4:00.0",
            identity_source="boot_pci",
            pci_bdf="0000:c4:00.0",
            memory_scope="amd_driver_vram_unclassified",
            total_bytes=96 * GIB,
            used_bytes=GIB,
        ),
    )
    if two_rtx:
        gpu += (
            GpuReading(
                vendor="nvidia",
                identity=GPU_B,
                identity_source="driver_uuid",
                pci_bdf="0000:04:00.0",
                memory_scope="dedicated_vram",
                total_bytes=48 * GIB,
                used_bytes=2 * GIB,
            ),
        )
    return HardwareReading(
        boot_id=BOOT,
        observed_at_ns=now,
        devices=gpu,
        host=HostReading(total_bytes=30 * GIB, available_bytes=24 * GIB),
        issues=(),
    )


def _processes(
    *,
    ticks: int | None = BIRTH,
    boot: str | None = BOOT,
    uuid: str = GPU_A,
    hardware_ns: int = 1000,
    observed_ns: int = 1010,
) -> ProcessObservation:
    return ProcessObservation(
        boot_id=boot,
        hardware_observed_at_ns=hardware_ns,
        observed_at_ns=observed_ns,
        scope="nvidia_compute_only",
        processes=(
            ComputeProcess(
                gpu_uuid=uuid, pid=PID, start_ticks=ticks, used_bytes=512 * 1024**2
            ),
        ),
        issues=("partial_compute_process_inventory",),
    )


def _rm(*, active: bool = True, job: int = 17):
    return {"lease_count": 1, "leases": [{"job_id": job, "external_in_use": active}]}


def _claim(*, job: int = 17, ticks: int = BIRTH, boot: str = BOOT, gpu: str = GPU_A):
    return ProcessLeaseClaim(
        job_id=job,
        gpu_uuid=gpu,
        pid=PID,
        start_ticks=ticks,
        boot_id=boot,
    )


def _stat(pid: int, *, name: str = "test ) worker", ticks: int = BIRTH) -> str:
    return f"{pid} ({name}) S " + " ".join(["0"] * 18 + [str(ticks)] + ["0"] * 4)


def _drm(tmp_path: Path):
    root = tmp_path / "drm"
    root.mkdir()
    pci = tmp_path / "pci" / "0000:c4:00.0"
    pci.mkdir(parents=True)
    (pci / "vendor").write_text("0x1002\n")
    (pci / "mem_info_vram_total").write_text(str(96 * GIB))
    (pci / "mem_info_vis_vram_total").write_text(str(96 * GIB))
    (pci / "mem_info_gtt_total").write_text(str(16 * GIB))
    (pci / "mem_info_gtt_used").write_text(str(GIB))
    (root / "card0").mkdir()
    (root / "card0" / "device").symlink_to(pci, target_is_directory=True)
    (root / "card0-DP-1").mkdir()
    return root, pci


def test_read_linux_proc_stat_with_embedded_parenthesis():
    assert parse_proc_start_ticks(_stat(PID), PID) == BIRTH
    assert parse_proc_start_ticks(_stat(PID, name="gpu (strange) name)"), PID) == BIRTH


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not-proc-data",
        _stat(PID + 1),
        _stat(PID, ticks=0),
        _stat(PID, ticks=-1),
        _stat(PID)[:-15],
    ],
)
def test_malformed_proc_stat_cannot_prove_pid_birth(text):
    with pytest.raises(ValueError):
        parse_proc_start_ticks(text, PID)


def test_nvidia_compute_parser_handles_gpus_and_unknown_used_vram():
    parsed = parse_compute_csv(
        f"{GPU_B}, 4321, N/A\n{GPU_A}, 4321, 1024"
    )
    assert parsed == ((GPU_A, 4321, GIB), (GPU_B, 4321, None))


@pytest.mark.parametrize(
    "row",
    [
        "totally invalid",
        f"{GPU_A}, 0, 100",
        f"{GPU_A}, -5, 100",
        f"{GPU_A}, notpid, 100",
        f"GPU-N/A, 4321, 100",
        f"{GPU_A}, 4321, -100",
        f"{GPU_A}, 4321, bad",
        f"{GPU_A}, 4321",
        f"{GPU_A}, 4321, 1\n{GPU_A}, 4321, 2",
        "X" * (32 * 1024 + 1),
    ],
)
def test_reject_bad_or_ambiguous_nvidia_process_rows(row):
    with pytest.raises(ValueError):
        parse_compute_csv(row)


def test_empty_compute_list_is_not_a_quiescence_proof():
    sample = collect_compute_processes(
        _hardware(),
        query=lambda: "",
        read_stat=lambda pid: _stat(pid),
        now_ns=lambda: 1010,
    )
    assert sample.processes == ()
    assert "partial_compute_process_inventory" in sample.issues
    assert sample.authorizes_execution is False
    result = summarize_ownership(_hardware(), sample, _rm(), now_ns=1011)
    assert result["result"] == "UNKNOWN"
    assert "gpu_context_closure_unverified" in result["reason_codes"]


def test_compute_row_binds_to_proc_birth_ticks_without_claiming_lease():
    sample = collect_compute_processes(
        _hardware(),
        query=lambda: f"{GPU_A}, {PID}, 100",
        read_stat=lambda pid: _stat(pid),
        now_ns=lambda: 1012,
    )
    assert sample.processes[0].start_ticks == BIRTH
    assert sample.processes[0].used_bytes == 100 * 1024**2
    result = summarize_ownership(_hardware(), sample, _rm(), now_ns=1013)
    assert result["candidate_lease_process_pairs"] == 0
    assert result["unmatched_compute_processes"] == 1
    assert result["lease_process_attribution"] == "unverified"


def test_vanished_pid_is_kept_as_uncertain_process_not_dropped():
    def vanished(pid):
        raise FileNotFoundError("PID disappeared during query")

    sample = collect_compute_processes(
        _hardware(),
        query=lambda: f"{GPU_A}, {PID}, N/A",
        read_stat=vanished,
        now_ns=lambda: 1012,
    )
    assert len(sample.processes) == 1
    assert sample.processes[0].start_ticks is None
    assert "process_birth_identity_unavailable" in sample.issues
    result = summarize_ownership(
        _hardware(), sample, _rm(), (_claim(),), now_ns=1013
    )
    assert result["candidate_lease_process_pairs"] == 0
    assert result["authorizes_execution"] is False


def test_unrecognized_gpu_uuid_is_not_attributed_to_known_gpu():
    sample = collect_compute_processes(
        _hardware(),
        query=lambda: f"{GPU_B}, {PID}, 150",
        read_stat=lambda pid: _stat(pid),
        now_ns=lambda: 1010,
    )
    assert sample.processes == ()
    assert "compute_gpu_uuid_not_in_hardware" in sample.issues


def test_candidate_requires_full_identity_and_active_external_lease():
    sample = _processes()
    result = summarize_ownership(
        _hardware(), sample, _rm(), (_claim(),), now_ns=1020
    )
    assert result["candidate_lease_process_pairs"] == 1
    assert result["unmatched_compute_processes"] == 0
    assert result["result"] == "UNKNOWN"
    assert result["authorizes_execution"] is False
    assert "candidates_not_verified_ownership" in result["reason_codes"]


@pytest.mark.parametrize(
    "claims,leases",
    [
        ((_claim(job=55),), _rm()),
        ((_claim(ticks=BIRTH + 1),), _rm()),
        ((_claim(boot="different-boot"),), _rm()),
        ((_claim(gpu=GPU_B),), _rm()),
        ((_claim(),), _rm(active=False)),
        ((), _rm()),
    ],
)
def test_stale_or_forged_candidate_cannot_be_verified(claims, leases):
    result = summarize_ownership(
        _hardware(two_rtx=True), _processes(), leases, claims, now_ns=1020
    )
    assert result["candidate_lease_process_pairs"] == 0
    assert result["unmatched_compute_processes"] == 1
    assert not result["authorizes_execution"]


def test_competing_claims_are_ambiguous_not_proven():
    leases = {"lease_count": 2, "leases": [
        {"job_id": 17, "external_in_use": True},
        {"job_id": 18, "external_in_use": True},
    ]}
    result = summarize_ownership(
        _hardware(), _processes(), leases,
        (_claim(), _claim(job=18)), now_ns=1020,
    )
    assert result["candidate_lease_process_pairs"] == 0
    assert "ambiguous_owner_claims" in result["reason_codes"]


@pytest.mark.parametrize(
    "leases",
    [
        None,
        {"lease_count": 1, "leases": []},
        {"lease_count": True, "leases": []},
        {"lease_count": 2, "leases": [{"job_id": 1, "external_in_use": True}]},
        {"lease_count": 1, "leases": [{"job_id": "1", "external_in_use": True}]},
    ],
)
def test_broken_rm_snapshot_rejects_candidate(leases):
    result = summarize_ownership(
        _hardware(), _processes(), leases, (_claim(),), now_ns=1020
    )
    assert result["candidate_lease_process_pairs"] == 0
    assert result["result"] == "UNKNOWN"


@pytest.mark.parametrize("delta", [-1000, 6000000000])
def test_bad_epoch_or_staleness_never_matches(delta):
    sample = _processes()
    hardware = replace(_hardware(), observed_at_ns=1000 + delta)
    result = summarize_ownership(
        hardware, sample, _rm(), (_claim(),), now_ns=1020
    )
    assert result["candidate_lease_process_pairs"] == 0
    assert result["authorizes_execution"] is False


def test_two_gpu_processes_are_never_summed_as_one_gpu_budget():
    sample = replace(
        _processes(),
        processes=_processes().processes + (
            ComputeProcess(
                gpu_uuid=GPU_B, pid=PID, start_ticks=BIRTH, used_bytes=2 * GIB
            ),
        ),
    )
    result = summarize_ownership(
        _hardware(two_rtx=True), sample, _rm(), (_claim(),), now_ns=1020
    )
    assert result["observed_compute_processes"] == 2
    assert result["candidate_lease_process_pairs"] == 1
    assert result["unmatched_compute_processes"] == 1
    assert result["lease_process_attribution"] == "unverified"
    assert result["authorizes_execution"] is False


def test_status_has_no_private_pid_uuid_or_boot_string():
    sample = _processes()
    summary = summarize_ownership(
        _hardware(), sample, _rm(), (_claim(),), now_ns=1020
    )
    text = json.dumps(summary)
    assert str(PID) not in text
    assert GPU_A not in text and BOOT not in text
    assert "boot-pci" not in text
    assert "lease_process_attribution" in text


def test_read_amd_aperture_separates_non_additive_vram_visible_gtt(tmp_path):
    root, _ = _drm(tmp_path)
    snapshot = collect_amd_apertures(
        _hardware(), drm_root=root, now_ns=lambda: 1010
    )
    assert snapshot.issues == ()
    assert snapshot.apertures[0].vram_bytes == 96 * GIB
    assert snapshot.apertures[0].visible_vram_bytes == 96 * GIB
    assert snapshot.apertures[0].gtt_bytes == 16 * GIB
    summary = summarize_memory_relation(_hardware(), snapshot, now_ns=1020)
    assert summary["memory_domain_mapping"] == "unverified"
    assert "amd_vram_exceeds_cpu_visible_ram" in summary["reason_codes"]
    assert summary["amd_apertures"][0]["gtt_aperture_bytes"] == 16 * GIB
    assert summary["authorizes_execution"] is False


def test_missing_or_invalid_gtt_never_becomes_available_ram(tmp_path):
    root, pci = _drm(tmp_path)
    (pci / "mem_info_gtt_total").unlink()
    observation = collect_amd_apertures(_hardware(), drm_root=root, now_ns=lambda: 1010)
    assert "amd_aperture_counters_incomplete" in observation.issues
    summary = summarize_memory_relation(_hardware(), observation, now_ns=1020)
    assert summary["memory_domain_mapping"] == "unverified"
    assert "incomplete_amd_memory_evidence" in summary["reason_codes"]


def test_amd_aperture_alias_does_not_create_second_memory_pool(tmp_path):
    root, pci = _drm(tmp_path)
    (root / "card2").mkdir()
    (root / "card2" / "device").symlink_to(pci, target_is_directory=True)
    snapshot = collect_amd_apertures(_hardware(), drm_root=root, now_ns=lambda: 1010)
    assert len(snapshot.apertures) == 1
    assert "amd_duplicate_pci" in snapshot.issues
    assert summarize_memory_relation(
        _hardware(), snapshot, now_ns=1020
    )["memory_domain_mapping"] == "unverified"


def test_no_automatic_discovery_in_pure_status_wrapper(monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("no OS process discovery during GET /status")

    with monkeypatch.context() as guard:
        guard.setattr(subprocess, "run", forbidden)
        result = observe_ownership_sources(
            lambda: _hardware(),
            lambda: _processes(),
            _rm(),
            claims_source=lambda: (_claim(),),
            now_ns=lambda: 1020,
        )
    assert result["candidate_lease_process_pairs"] == 1
    assert result["authorizes_execution"] is False


def test_source_exception_is_redacted_and_not_authorizing():
    def failing():
        raise RuntimeError("secret-owner-token")

    summary = observe_ownership_sources(
        failing, lambda: _processes(), _rm(), now_ns=lambda: 1020
    )
    assert summary["result"] == "UNKNOWN"
    assert summary["reason_codes"] == ["ownership_source_error"]
    assert "secret-owner-token" not in json.dumps(summary)


def _app(tmp_path, *, enabled: bool, hardware_source=None, process_source=None):
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"models": []}, request=request)
    return create_gateway_app(
        Settings(
            _env_file=None,
            gateway_resource_ownership_observation_enabled=enabled,
            gateway_gpu_marker=tmp_path / "gpu.marker",
        ),
        upstream_transport=httpx.MockTransport(handler),
        resource_hardware_source=hardware_source,
        resource_process_source=process_source,
    )


@pytest.mark.anyio
async def test_existing_gateway_default_off_never_reads_owner_sources(tmp_path):
    calls = []

    def forbidden():
        calls.append(1)
        raise AssertionError("disabled source was invoked")

    app = _app(tmp_path, enabled=False, hardware_source=forbidden, process_source=forbidden)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            status = (await client.get("/status")).json()
            assert "resource_ownership" not in status
            assert status["active_count"] == 0
            assert not calls


@pytest.mark.anyio
async def test_optional_gateway_ownership_is_unknown_and_lease_unchanged(tmp_path):
    # Real RM snapshots do not expose PID/birth/GPU ownership.
    app = _app(
        tmp_path,
        enabled=True,
        hardware_source=lambda: replace(_hardware(), observed_at_ns=time.monotonic_ns()),
        process_source=lambda: replace(
            _processes(),
            observed_at_ns=time.monotonic_ns(),
            hardware_observed_at_ns=1000,
        ),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            status = (await client.get("/status")).json()
            assert status["resource_ownership"]["result"] == "UNKNOWN"
            assert status["resource_ownership"]["authorizes_execution"] is False
            assert "resource_ownership" not in (await client.get("/health")).json()
            lease = await client.post(
                "/resource/leases", json={"priority": 50, "source": "manual-lease"}
            )
            assert lease.status_code == 201
            current = (await client.get("/status")).json()
            assert current["active_count"] == 1
            assert current["resource_ownership"]["result"] == "UNKNOWN"
            await client.delete(f"/resource/leases/{lease.json()['lease_id']}")
            assert (await client.get("/status")).json()["active_count"] == 0


@pytest.mark.anyio
async def test_concurrent_status_requests_cannot_create_gpu_authorization(tmp_path):
    sample_hardware = replace(_hardware(), observed_at_ns=time.monotonic_ns())
    sample_proc = replace(
        _processes(),
        observed_at_ns=time.monotonic_ns(),
        hardware_observed_at_ns=sample_hardware.observed_at_ns,
    )
    app = _app(
        tmp_path, enabled=True,
        hardware_source=lambda: sample_hardware,
        process_source=lambda: sample_proc,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            initial = (await client.get("/status")).json()
            responses = await asyncio.gather(*(client.get("/status") for _ in range(8)))
            assert all(r.status_code == 200 for r in responses)
            assert all(not r.json()["resource_ownership"]["authorizes_execution"] for r in responses)
            after = (await client.get("/status")).json()
            assert after["resource_manager"] == initial["resource_manager"]
            assert after["active_count"] == initial["active_count"]
