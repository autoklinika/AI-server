"""Static fail-closed acceptance tests for uninstalled system-manager DEV profiles."""
from pathlib import Path
import ast
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]/"deploy/physical-ollama-routing-dev"
SYSTEMD=ROOT/"systemd"

def parse_unit(name):
    result={}
    for line in (SYSTEMD/name).read_text().splitlines():
        s=line.strip()
        if "=" not in s or s.startswith("#"):
            continue
        key,val=s.split("=",1)
        result.setdefault(key,[]).append(val)
    return result

@pytest.mark.parametrize("gpu,name,expected,forbidden,memmax,port",[
    ("amd","ai-rm-ollama-amd-dev.service",
     "/dev/dri/renderD128",("/dev/nvidia0","/dev/nvidiactl","/dev/kfd","/dev/dri/renderD129"),
     "6G","11646"),
    ("rtx","ai-rm-ollama-rtx-dev.service",
     "/dev/nvidia0",("/dev/kfd","/dev/dri/renderD128","/dev/dri/renderD129"),
     "4G","11647"),
])
def test_static_sandbox_isolation_and_budgets(
    gpu,name,expected,forbidden,memmax,port,
):
    u=parse_unit(name)
    def value(key):return u[key][0]
    assert value("DevicePolicy")=="closed"
    assert value("NoNewPrivileges")=="yes"
    assert value("User")=="ollama"
    assert value("Group")=="ollama"
    assert value("PrivateDevices")=="no"
    assert value("ProtectSystem")=="strict"
    assert value("MemoryAccounting")=="yes"
    assert value("MemoryMax")==memmax
    assert value("MemorySwapMax")=="0"
    assert value("TasksMax")=="128"
    assert value("KillMode")=="control-group"
    assert value("Restart")=="no"
    assert value("RuntimeMaxSec")=="360"
    assert value("ExecStart")=="/usr/local/bin/ollama serve"
    assert any(item.startswith(expected+" ") for item in u["DeviceAllow"])
    assert all(not any(path in item for path in forbidden) for item in u["DeviceAllow"])
    assert f"OLLAMA_HOST=127.0.0.1:{port}" in u["Environment"]
    assert "OLLAMA_CONTEXT_LENGTH=4096" in u["Environment"]
    assert "OLLAMA_NO_CLOUD=true" in u["Environment"]
    assert "Install" not in (SYSTEMD/name).read_text()
    assert all(
        not item.startswith("OLLAMA_HOST=0.0.0.0")
        for item in u["Environment"]
    )
    assert "OLLAMA_VULKAN=1" in u["Environment"] if gpu=="amd" else "OLLAMA_VULKAN=0" in u["Environment"]

def test_rtx_waits_for_passed_gen3_ha_boot_gate():
    u=parse_unit("ai-rm-ollama-rtx-dev.service")
    assert "ai-egpu-gen3-ha.service" in u["After"]
    assert "ai-egpu-gen3-ha.service" in u["Requires"]

def test_permission_probe_is_read_only_without_gpu_compute():
    code=(ROOT/"os_gpu_access_probe.py").read_text()
    ast.parse(code)
    for term in ("os.open(", "O_NONBLOCK", "ACCESS_DENIED", "ACCESS_GRANTED",
                 "/dev/dri/renderD128","/dev/nvidia0","/dev/kfd",
                 "/system.slice/ai-rm-dev-"):
        assert term in code
    for forbidden in ("cudaMalloc","hipInit","ioctl(","modprobe","setpci","systemctl restart"):
        assert forbidden not in code

def test_operator_only_negative_bypass_script_does_not_install_services():
    code=(ROOT/"run_system_scope_gpu_negative_dev.sh").read_text()
    assert "systemd-run --system" in code
    assert "--property=DevicePolicy=closed" in code
    assert "--property=MemoryMax=96M" in code
    assert "--property=NoNewPrivileges=yes" in code
    assert "--uid=harrypotter" in code
    assert "--collect" in code and "--wait" in code
    assert "--property=Restart=no" in code
    assert "SYSTEM_SCOPE_FIXED_GPU_DEVICE_ALLOW_DENY_PASS" in code
    assert "GLOBAL_HOST_GPU_EXCLUSIVITY=NOT_VERIFIED" in code
    for forbidden in ("systemctl stop ","systemctl restart ","systemctl enable ",
                      "update-grub","modprobe","setpci","nvidia-smi -pl", "rmmod",
                      "sudo -n","--user "):
        assert forbidden not in code
    completed=subprocess.run(["bash","-n",str(ROOT/"run_system_scope_gpu_negative_dev.sh")],
        capture_output=True,text=True,timeout=3)
    assert completed.returncode==0,completed.stderr
