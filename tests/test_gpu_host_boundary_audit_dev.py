"""CPU-only negative tests: bounded transient GPU access != global exclusivity."""
from pathlib import Path
import subprocess

import pytest

from ai_bridge.gateway import gpu_host_boundary_audit_dev as audit

def _node(path: str):
    if path=="/dev/nvidia0":
        return {"state":"OBSERVED","world_write":True,"mode":"0666"}
    return {"state":"OBSERVED","world_write":False,"mode":"0660"}

def _unit(name: str):
    return {
        "LoadState":"loaded",
        "ActiveState":"active" if name=="comfyui.service" else "inactive",
        "DevicePolicy":"auto" if name=="comfyui.service" else "closed",
        "MainPID":"4937" if name=="comfyui.service" else "0",
    }

def _owners():
    return {"state":"OBSERVED_PARTIAL","pids":[4937],
            "cgroups":{"4937":"/system.slice/comfyui.service"},
            "coverage":"PARTIAL_VISIBLE_USERS_ONLY"}

def _good_hardware(tmp_path):
    for bdf,vendor,device in [
        ("0000:c6:00.0","0x1002","0x150e"),
        ("0000:03:00.0","0x10de","0x2d04"),
    ]:
        path=tmp_path/bdf
        path.mkdir()
        (path/"vendor").write_text(vendor)
        (path/"device").write_text(device)

def test_explicit_scope_pass_still_blocks_global_grant(tmp_path):
    _good_hardware(tmp_path)
    result=audit.audit(node=_node,unit=_unit,holders=_owners,
                       direct_api=lambda:"REACHABLE_DIRECT",
                       pci_root=tmp_path)
    assert result["decision"]=="BLOCKED"
    assert result["global_host_gpu_exclusivity"]=="NOT_VERIFIED"
    assert result["driver_reuse_safe"]=="NOT_VERIFIED"
    assert result["n1_gpu_grant"]=="NOT_ADMITTED"
    assert result["transient_systemd_scope_test"]=="PASS_REPORTED_SEPARATELY"
    assert result["checks"]["hardware"]=={
        "0000:c6:00.0":"IDENTITY_MATCH",
        "0000:03:00.0":"IDENTITY_MATCH",
    }
    assert set(result["findings"])=={
        "WORLD_WRITABLE_GPU_DEVICE",
        "ACTIVE_SERVICE_GPU_ACCESS_NOT_CGROUP_RESTRICTED",
        "GPU_FILE_DESCRIPTORS_OBSERVED",
        "DIRECT_OLLAMA_API_REACHABLE_OUTSIDE_GATEWAY",
    }

def test_empty_observations_cannot_be_misinterpreted_as_safe(tmp_path):
    _good_hardware(tmp_path)
    result=audit.audit(node=lambda p:{"state":"OBSERVED","world_write":False},
         unit=lambda s:{"ActiveState":"inactive","DevicePolicy":"closed"},
         holders=lambda:{"state":"OBSERVED_PARTIAL","pids":[]},
         direct_api=lambda:"UNKNOWN",pci_root=tmp_path)
    assert result["findings"]==[]
    assert result["decision"]=="BLOCKED"
    assert result["global_host_gpu_exclusivity"]=="NOT_VERIFIED"

@pytest.mark.parametrize("failure",["node","unit","holder","api"])
def test_unknown_or_unreadable_evidence_never_allows_gpu(failure,tmp_path):
    _good_hardware(tmp_path)
    def boom(*_):
        raise PermissionError("hidden GPU data")
    result=audit.audit(
        node=boom if failure=="node" else _node,
        unit=boom if failure=="unit" else _unit,
        holders=boom if failure=="holder" else _owners,
        direct_api=boom if failure=="api" else (lambda:"REACHABLE_DIRECT"),
        pci_root=tmp_path,
    )
    assert result["decision"]=="BLOCKED"
    assert result["driver_reuse_safe"]=="NOT_VERIFIED"
    if failure=="node":
        assert result["checks"]["gpu_nodes"]["/dev/nvidia0"]["state"]=="UNKNOWN"
    if failure=="holder":
        assert result["checks"]["open_gpu_holders"]["state"]=="UNKNOWN"

def test_wrong_hardware_identity_never_grants(tmp_path):
    _good_hardware(tmp_path)
    (tmp_path/"0000:c6:00.0"/"device").write_text("0x9999")
    result=audit.audit(node=_node,unit=_unit,holders=_owners,
                       direct_api=lambda:"UNKNOWN",pci_root=tmp_path)
    assert result["checks"]["hardware"]["0000:c6:00.0"]=="MISMATCH"
    assert result["decision"]=="BLOCKED"

def test_no_process_commands_or_hardware_writes_in_boundary_code():
    source=Path(audit.__file__).read_text()
    for token in ("os.kill(","modprobe","setpci","systemctl stop",
                  "systemctl restart","/dev/nvidia0", "DIRECT_OLLAMA"):
        if token in ("/dev/nvidia0","DIRECT_OLLAMA"):
            assert token in source
        else:
            assert token not in source
    assert "return 2" in source

def test_transient_evidence_files_have_real_expected_denials():
    logs=Path("/srv/ai-data/staging/gpu-dual-route-20261023")
    amd=logs/"system-scope-negative-amd.log"
    rtx=logs/"system-scope-negative-rtx.log"
    if not amd.is_file() or not rtx.is_file():
        pytest.skip("host-only external operator evidence not mounted in CI")
    a=amd.read_text()
    b=rtx.read_text()
    assert "SYSTEM_SCOPE_DEVICE_BOUNDARY_PASS amd" in a
    assert "'/dev/dri/renderD128': 'ACCESS_GRANTED'" in a
    assert "'/dev/nvidia0': 'ACCESS_DENIED'" in a
    assert "SYSTEM_SCOPE_DEVICE_BOUNDARY_PASS rtx" in b
    assert "'/dev/nvidia0': 'ACCESS_GRANTED'" in b
    assert "'/dev/dri/renderD128': 'ACCESS_DENIED'" in b
    assert "Finished with result: success" in a
    assert "Finished with result: success" in b
