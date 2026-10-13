"""End-to-end parked Vision runner handshake against a local test Gateway.

No PyTorch, no GPU, no production API. Validates that the worker cannot
execute until admission, then exits before the external use is released.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from ai_bridge.benchmarks.vision_rm_executor import VisionExecutionError, call


class FakeGateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def reply(self, code, payload):
        data=json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        s=self.server.state
        if self.path=="/status":
            return self.reply(200, {"admission_blocked":False,
                      "gpu_residency":{"recovery_required":False}})
        if self.path=="/resource/leases/DEV":
            return self.reply(200,{"state":"active"})
        if self.path=="/resource/leases/DEV/uses/USE" and s["use"]:
            return self.reply(200,{"provider":"vision-local","capability":"image-analysis"})
        return self.reply(404,{"error":"not_found"})

    def do_POST(self):
        s=self.server.state
        size=int(self.headers.get("Content-Length","0"))
        body=json.loads(self.rfile.read(size) or b"{}")
        if self.path=="/resource/leases":
            assert body["workload"]=="vision-benchmark"
            assert body["priority_class"]=="background"
            s["lease"]=True
            return self.reply(201,{"lease_id":"DEV","state":"active"})
        if self.path=="/resource/leases/DEV/uses":
            assert s["lease"]
            pid=body["worker_pid"]
            assert isinstance(pid,int) and pid>1
            assert body["provider"]=="vision-local"
            assert body["capability"]=="image-analysis"
            if "scope_path" in body:
                from ai_bridge.gateway.vision_residency_evidence import worker_cgroup_path
                assert body["scope_path"]==worker_cgroup_path(pid)
            assert not s["output"].exists(), "worker started before GPU authorization"
            os.kill(pid,0)
            s["worker_pid"]=pid
            s["use"]=True
            return self.reply(201,{"use_id":"USE"})
        if self.path=="/resource/leases/DEV/heartbeat":
            assert s["lease"]
            return self.reply(200,{"state":"active"})
        return self.reply(404,{})

    def do_DELETE(self):
        s=self.server.state
        if self.path=="/resource/leases/DEV/uses/USE":
            assert s["use"]
            # Parent has reaped the worker before requesting cleanup.
            with self.assert_dead(s["worker_pid"]):
                pass
            s["use"]=False
            s["cleaned"]=True
            return self.reply(200,{"released":True})
        if self.path=="/resource/leases/DEV":
            assert not s["use"]
            s["lease"]=False
            return self.reply(200,{"released":True})
        return self.reply(404,{})

    from contextlib import contextmanager
    @contextmanager
    def assert_dead(self,pid):
        try:
            os.kill(pid,0)
        except ProcessLookupError:
            yield
        else:
            raise AssertionError("worker was not reaped before cleanup")


class ScopedExecutorRealCgroupTest(unittest.TestCase):
    def test_systemd_scope_worker_is_parked_and_cleans_up(self):
        import shutil
        from ai_bridge.benchmarks.vision_rm_scoped_executor import ScopedVisionExecutor
        if (not shutil.which("systemd-run") or not
                Path(f"/run/user/{os.getuid()}/bus").is_socket()):
            self.skipTest("systemd user bus unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            output=root/"marker.json"
            script=root/"worker.py"
            script.write_text("from pathlib import Path\nimport sys,json\n"+
                              "Path(sys.argv[1]).write_text(json.dumps({'worker':'scoped'}))\n")
            server=ThreadingHTTPServer(("127.0.0.1",0),FakeGateway)
            server.state={"output":output,"lease":False,"use":False,
                          "cleaned":False,"worker_pid":None}
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                result=ScopedVisionExecutor(base=f"http://127.0.0.1:{server.server_port}").execute(
                    python=Path(sys.executable),script=script,args=[str(output)],
                    log=root/"scoped.log",max_seconds=15)
                self.assertEqual(result["status"],"completed")
                self.assertEqual(json.loads(output.read_text()),{"worker":"scoped"})
                self.assertTrue(server.state["cleaned"])
                self.assertFalse(server.state["lease"])
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
