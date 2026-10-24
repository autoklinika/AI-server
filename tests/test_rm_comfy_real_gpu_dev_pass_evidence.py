"""CPU-only verification of scope-limited real AMD ComfyUI DEV acceptance.

The persisted JSON is sanitized evidence from a read-only collector.
The original output PNG is not published in the public Git repository.
"""
import hashlib
import json
from pathlib import Path
import re

import pytest

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/reports/RM_COMFY_GPU_REAL_DEV_PASS_2026-10-23.json"
REPORT=ROOT/"docs/reports/RM_COMFY_GPU_REAL_ON_DEMAND_ACCEPTANCE_2026-10-23_PL.md"

def result():
    return json.loads(EVIDENCE.read_text())

def test_machine_attested_real_dev_success_without_production_cutover():
    x=result()
    assert x["schema"]==1
    assert x["verdict"]=="REAL_COMFY_GPU_DEV_ONDEMAND_AND_PRODUCTION_ROLLBACK_PASS"
    assert x["production_cutover"]=="NOT_DEPLOYED"
    assert "AMD Radeon 890M" in x["physical_GPU_backend"]
    assert "VAE" in x["vae_backend"] or "cuda:0" in x["vae_backend"]
    assert x["generated_image"]["dimensions_px"]==[64,64]
    assert x["generated_image"]["file_size_bytes"]>1000
    assert re.fullmatch(r"[a-f0-9]{64}",x["generated_image"]["sha256"])
    assert x["generated_image"]["public_repository_copy"] is False
    assert x["vae_prompt_duration_s"]>0

def test_service_cleanup_and_host_restoration_are_explicit():
    x=result()
    assert x["system_manager_service"]["final_active_state"]=="inactive"
    assert x["system_manager_service"]["final_mainpid"]=="0"
    assert x["system_manager_service"]["end_port_11657"]=="CLOSED"
    assert x["system_watchdog"]["end_state"]=="inactive"
    assert x["existing_rm_lifecycle"]["end_rm_state"]=="IDLE"
    assert x["existing_rm_lifecycle"]["end_scheduler"]=={"active":0,"queued":0}
    assert x["existing_rm_lifecycle"]["dev_recovery_marker_present"] is False
    assert x["production_restoration"]["gateway"]=="active"
    assert x["production_restoration"]["comfyui"]=="active"
    assert x["production_restoration"]["ollama"]=="active"
    assert x["production_restoration"]["comfyui_ready_log"]=="PASS"
    assert x["production_restoration"]["gateway_rm_health"]=="PASS"
    assert x["production_restoration"]["comfyui_residency_models"]==0
    assert x["nvidia_postflight"]["memory_used_mib"]<=256
    assert x["nvidia_postflight"]["pstate"]=="P8"
    assert x["nvidia_postflight"]["pci_express"]=="Gen3x4"
    for errors in x["nvidia_postflight"]["pcie_aer_counters"].values():
        assert all(y==0 for y in errors.values())

def test_not_a_green_card_for_gpu_driver_safe_reuse_or_n1():
    x=result()
    assert x["existing_rm_lifecycle"]["independent_real_GPU_reuse_safe"]=="NOT_VERIFIED"
    assert any("GPU_REUSE_SAFE" in v for v in x["unverified_conditions"])
    assert len(x["unverified_conditions"])>=4
    assert x["production_cutover"]=="NOT_DEPLOYED"
    txt=REPORT.read_text()
    assert "NOT_VERIFIED" in txt and "NOT_ADMITTED" in txt
    assert "one-shot" in txt.lower() or "jednorazow" in txt.lower()
    assert "text-to-image" in txt
    assert "NO-GO" in txt

def test_local_png_hash_when_file_is_available():
    x=result()
    source=Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023")/x["generated_image"]["relative_source"]
    if not source.exists():
        pytest.skip("Original image is kept only on the physical AI Platform host")
    data=source.read_bytes()
    assert data[:8]==b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(data[16:20],"big")==64
    assert int.from_bytes(data[20:24],"big")==64
    assert len(data)==x["generated_image"]["file_size_bytes"]
    assert hashlib.sha256(data).hexdigest()==x["generated_image"]["sha256"]

def test_no_embedded_secrets_or_private_raw_log_records():
    data=EVIDENCE.read_text()
    for pattern in (r"gh[pousr]_[A-Za-z0-9_]{16,}",
                    r"github_pat_[A-Za-z0-9_]{16,}",
                    r"-----BEGIN .*PRIVATE KEY-----",
                    r"\bsk-[A-Za-z0-9_-]{30,}\b",
                    r"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b"):
        assert not re.search(pattern,data)
    assert "BEGIN PRIVATE KEY" not in data
    assert "root_owned_raw_operator_logs" in data
