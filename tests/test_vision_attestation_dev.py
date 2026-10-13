"""Actual /proc attestation against parked child, without GPU or HTTP use."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ai_bridge.gateway.vision_attestation import attest_worker
from ai_bridge.benchmarks import vision_worker_gate


def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_only_pinned_script_is_admitted():
    with tempfile.TemporaryDirectory() as td:
        script=Path(td)/"trusted.py"
        script.write_text("print('only after token')\n")
        gate=Path(vision_worker_gate.__file__).resolve()
        read_fd,write_fd=os.pipe()
        try:
            child=subprocess.Popen(
                [sys.executable,str(gate),"--gate-fd",str(read_fd),
                 "--gateway","http://127.0.0.1:1",
                 "--python",sys.executable,"--script",str(script)],
                pass_fds=(read_fd,),stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            os.close(read_fd)
            read_fd=-1
            # The gate is blocked on a private pipe. Model was NOT run.
            import time
            deadline=time.monotonic()+3
            while not Path(f"/proc/{child.pid}/cmdline").read_bytes().count(b"vision_worker_gate.py"):
                if time.monotonic()>=deadline:raise AssertionError("worker not ready")
                time.sleep(.01)
            allow={str(script.resolve()):sha(script)}
            assert attest_worker(child.pid,allow,{})
            assert not attest_worker(child.pid,{}, {})
            assert not attest_worker(child.pid,{str(script.resolve()):"f"*64},{})
            script.write_text("print('tampered')\n")
            assert not attest_worker(child.pid,allow,{})
        finally:
            if read_fd>=0:os.close(read_fd)
            os.close(write_fd)
            child.terminate()
            child.wait(timeout=5)
