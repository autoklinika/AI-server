"""Real Linux systemd-scope failure handling, no accelerator or production calls.

Only a localhost fake Gateway is used. Scope and descendant termination are
verified by actual systemd user-manager and cgroup.procs.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from ai_bridge.benchmarks.vision_rm_executor import VisionExecutionError
from ai_bridge.benchmarks.vision_rm_scoped_executor import ScopedVisionExecutor
from test_vision_rm_executor_dev import FakeGateway


class FailingGateway(FakeGateway):
    def do_POST(self):
        if self.path=="/resource/leases/DEV/heartbeat" and self.server.state.get("deny_heartbeat") and self.server.state.get("use"):
            self.server.state["heartbeat_failed"]=True
            return self.reply(503, {"error":"simulated_heartbeat_loss"})
        return super().do_POST()


@unittest.skipUnless(shutil.which("systemd-run") is not None
    and Path(f"/run/user/{os.getuid()}/bus").is_socket(),
    "systemd --user unavailable")
class ScopedVisionFailureTests(unittest.TestCase):
    def run_case(self, script_code: str, *, timeout: int=15, deny_heartbeat: bool=False):
        with tempfile.TemporaryDirectory(prefix="vision-fault-tests-") as temp:
            root=Path(temp)
            output=root/"created_after_authorization.json"
            script=root/"worker.py"
            script.write_text(script_code,encoding="utf-8")
            server=ThreadingHTTPServer(("127.0.0.1",0),FailingGateway)
            server.state={"output":output, "lease":False,"use":False,
                          "cleaned":False,"worker_pid":None,
                          "deny_heartbeat":deny_heartbeat,"heartbeat_failed":False}
            t=threading.Thread(target=server.serve_forever,daemon=True)
            t.start()
            try:
                try:
                    ScopedVisionExecutor(base=f"http://127.0.0.1:{server.server_port}").execute(
                        python=Path(sys.executable),script=script,args=[str(output)],
                        log=root/"test-executor.log",max_seconds=timeout)
                    self.fail("a deliberately failing GPU worker must NOT report success")
                except VisionExecutionError:
                    pass
                assert server.state["cleaned"], ("GPU external use not cleaned",server.state)
                assert not server.state["lease"],("stale shared RM lease",server.state)
                assert not server.state["use"],("stale Vision use",server.state)
                if deny_heartbeat:
                    self.assertTrue(server.state["heartbeat_failed"])
                # Check the systemd cgroup is already gone, not merely a dead parent.
                uid=os.getuid()
                cgbase=Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice")
                for candidate in cgbase.glob("vision-bench-*.scope"):
                    try:
                        members=candidate.joinpath("cgroup.procs").read_text().strip()
                    except FileNotFoundError:
                        continue
                    self.assertEqual(members,"",f"scope still has live members: {candidate}")
                return output.exists()
            finally:
                server.shutdown();server.server_close();t.join(timeout=2)

    def test_child_sigkill_fails_job_but_cleanup_releases_gpu(self):
        self.run_case(
            "import os,signal\n"
            "os.kill(os.getpid(),signal.SIGKILL)\n",
            timeout=12,
        )

    def test_executor_timeout_kills_scope_and_releases_gpu(self):
        self.run_case(
            "import time\n"
            "time.sleep(40)\n", timeout=10,
        )

    def test_lost_heartbeat_stops_worker_and_releases_gpu(self):
        self.run_case(
            "import time\n"
            "time.sleep(40)\n", timeout=18,deny_heartbeat=True,
        )

    def test_detached_descendant_cannot_escape_cgroup_cleanup(self):
        """Child calls setsid(), survives original PID but not the cgroup scope."""
        self.run_case(
            "import subprocess,sys,time\n"
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(35)'],"
            "start_new_session=True,stdin=subprocess.DEVNULL,"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            "time.sleep(.4)\n"
            "raise SystemExit(7)\n",
            timeout=10,
        )
