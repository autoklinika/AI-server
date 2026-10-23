"""Historical CPU-only systemd fault evidence; never claims AMD E_safe."""
import json
import hashlib
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"docs/reports/RM_COMFY_CPU_FAULTS_SYSTEMD_2026-10-24.json"


def test_true_systemd_failures_have_expected_separate_outcomes():
    j=json.loads(REPORT.read_text())
    assert j["status"]=="THREE_REAL_CPU_ONLY_SYSTEMD_FAULTS_PASS"
    assert j["scope"]=="DEV_REAL_USER_SYSTEMD_CPU_ONLY; NOT_ACTUAL_AMD_GPU_CRASH"
    assert j["gpu_driver_reuse_safe"]=="NOT_VERIFIED"
    assert j["n1_gpu_grant"]=="NOT_ADMITTED"
    assert j["production_modified"] is False
    outcomes={c["fault"]:c for c in j["cases"]}
    assert set(outcomes)=={"memory_limit","service_timeout","forced_termination"}
    assert "oom-kill" in outcomes["memory_limit"]["expected_result"]
    assert "timeout" in outcomes["service_timeout"]["expected_result"]
    assert "code=killed" in outcomes["forced_termination"]["expected_result"]
    for c in j["cases"]:
        assert c["evidence"]=="PASS"
        assert c["mainpid_after"]==0
        assert c["service_after"]=="inactive"
        assert len(c["log_sha256"])==64


def test_original_local_fault_logs_match_hashes_when_available():
    root=Path("/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024")
    if not root.exists():
        pytest.skip("Original systemd CPU trial data remain on AI Platform")
    j=json.loads(REPORT.read_text())
    files={"memory_limit":"memory-test.log","service_timeout":"timeout-test.log",
           "forced_termination":"signal-test.log"}
    for case in j["cases"]:
        logfile=root/files[case["fault"]]
        assert logfile.is_file()
        assert hashlib.sha256(logfile.read_bytes()).hexdigest()==case["log_sha256"]


def test_gpu_grant_is_still_not_allowed_even_when_cpu_faults_pass():
    s=REPORT.read_text()
    assert "NOT_VERIFIED" in s
    assert "NOT_ADMITTED" in s
    assert "NOT_ACTUAL_AMD_GPU_CRASH" in s
    assert "CPU_ONLY" in s
