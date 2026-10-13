"""Optional localhost DEV Gateway + real systemd scope integration test.

No GPU model is loaded. Skips on CI runners without an accessible user bus.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time

import httpx
import pytest
import uvicorn

from ai_bridge.benchmarks.vision_rm_scoped_executor import ScopedVisionExecutor
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_gpu_residency import Providers


def _available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_scoped_dev_runner_through_actual_gateway_endpoints():
    if not shutil.which("systemd-run") or not Path(f"/run/user/{os.getuid()}/bus").is_socket():
        pytest.skip("systemd user-manager scope not available on this runner")

    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        providers=Providers()
        settings=Settings(_env_file=None,
                          gateway_gpu_marker=root/"shared-gpu-blocked",
                          gateway_vision_external_enabled=True,
                          gateway_max_concurrency=4)
        app=create_gateway_app(
            settings,
            upstream_transport=httpx.MockTransport(providers.handle),
            residency_transport=httpx.MockTransport(providers.handle),
        )
        port=_available_port()
        server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,
                                            log_level="error",access_log=False))
        thread=threading.Thread(target=server.run,daemon=True)
        thread.start()
        try:
            start=time.monotonic()
            while not server.started:
                if time.monotonic()-start>10:
                    raise TimeoutError("DEV Gateway startup")
                time.sleep(.05)
            script=root/"tiny_worker.py"
            marker=root/"dummy-model-output.json"
            script.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                "Path(sys.argv[1]).write_text(json.dumps({'started_after_admission':True}))\n"
            )
            report=ScopedVisionExecutor(base=f"http://127.0.0.1:{port}").execute(
                python=Path(os.sys.executable),script=script,args=[str(marker)],
                log=root/"dev-e2e.log",max_seconds=20)
            assert report["status"]=="completed"
            assert json.loads(marker.read_text())=={"started_after_admission":True}
            assert not (root/"shared-gpu-blocked").exists()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}",trust_env=False) as api:
                status=api.get("/status").json()
            assert status["gpu_residency"]["state"]=="llm"
            assert status["resource_leases"]["lease_count"]==0
            assert status["active_count"]==0
            assert providers.models==[]
        finally:
            server.should_exit=True
            thread.join(timeout=8)
            assert not thread.is_alive(), "DEV Gateway failed to stop"
