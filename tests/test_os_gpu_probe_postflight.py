"""CPU-only regression of bounded KFD postflight in the operator script.

Extracts the exact shell block into a temporary copy and redirects only its
read-only KFD path to a fixture. Never invokes sudo/systemd-run or GPU devices.
"""
from pathlib import Path
import subprocess
import threading
import time

SOURCE = Path(__file__).resolve().parents[1] / "tools/run_rm_os_gpu_systemd_probe.sh"


def run_postflight(tmp_path, *, persisted=False, readable=True):
    raw = SOURCE.read_text()
    assert raw.count("echo 'STAGE 3: BOUNDED READ-ONLY KFD POSTFLIGHT'") == 1
    snippet = "echo 'STAGE 3: BOUNDED READ-ONLY KFD POSTFLIGHT'" + raw.split(
        "echo 'STAGE 3: BOUNDED READ-ONLY KFD POSTFLIGHT'", 1)[1]
    proc_dir = tmp_path / "proc"
    if readable:
        proc_dir.mkdir()
        (proc_dir / "123456789").mkdir()
    logdir = tmp_path / "out"
    logdir.mkdir()
    # Changes occur solely in this CPU fixture copy; production script remains fixed.
    snippet = snippet.replace("/sys/class/kfd/kfd/proc", str(proc_dir))
    snippet = snippet.replace("sleep 0.25", "sleep 0.005")
    script = tmp_path / "postflight.sh"
    script.write_text('set -euo pipefail\nfolder="' + str(logdir) + '"\n' + snippet)
    if readable and not persisted:
        def retire():
            time.sleep(0.025)
            (proc_dir / "123456789").rmdir()
        thread = threading.Thread(target=retire)
        thread.start()
    else:
        thread = None
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                            timeout=10)
    if thread is not None:
        thread.join(timeout=2)
    return result, (logdir / "kfd-postflight.log").read_text()


def test_delayed_cleanup_needs_three_sequential_empty_observations(tmp_path):
    result, log = run_postflight(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "pids=123456789" in log
    assert log.count("pids=none") >= 3
    assert "KFD_POSTFLIGHT=THREE_CONSECUTIVE_EMPTY_OBSERVATIONS" in result.stdout
    assert "GPU_REUSE_SAFE=NOT_VERIFIED" in result.stdout


def test_persistent_gpu_context_remains_blocked_and_records_pid(tmp_path):
    result, log = run_postflight(tmp_path, persisted=True)
    assert result.returncode == 2
    assert "pids=123456789" in log
    assert "KFD_POSTFLIGHT=UNVERIFIED" in result.stderr
    assert "GPU_REUSE_SAFE=NOT_VERIFIED" in result.stdout


def test_failed_kfd_read_fails_closed(tmp_path):
    result, log = run_postflight(tmp_path, readable=False)
    assert result.returncode == 2
    assert "KFD_READ_ERROR" in log
    assert "KFD_POSTFLIGHT=UNVERIFIED" in result.stderr
