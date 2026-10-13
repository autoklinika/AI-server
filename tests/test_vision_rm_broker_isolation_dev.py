"""Adversarial, no-GPU tests: controller bearer never crosses IPC to model."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time

import httpx
import pytest

from ai_bridge.benchmarks import vision_rm_broker
from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_gpu_residency import Providers


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeAPI:
    def __init__(self):
        self.calls=[]
        self.lease="PRIVATE_CONTROL_LEASE"
        self.current=None

    def __call__(self,base,method,path,payload=None):
        self.calls.append((method,path))
        if (method,path)==("POST","/resource/leases"):
            assert payload=={"source":"vision-broker","workload":"vision-benchmark",
                             "priority_class":"background"}
            self.current="queued"
            return {"lease_id":self.lease,"state":"queued"}
        if (method,path)==("GET",f"/resource/leases/{self.lease}"):
            self.current="active"
            return {"state":"active"}
        if (method,path)==("POST",f"/resource/leases/{self.lease}/uses"):
            assert payload["provider"]=="vision-local"
            assert payload["capability"]=="image-analysis"
            self.current="used"
            return {"use_id":"PRIVATE_USE_ID","worker_token":"read-only-use-token-is-not-rm-bearer-abcdef"}
        if (method,path)==("DELETE",f"/resource/leases/{self.lease}/uses/PRIVATE_USE_ID"):
            self.current="clean"
            return {"released":True}
        if (method,path)==("DELETE",f"/resource/leases/{self.lease}"):
            self.current=None
            return {"released":True}
        if (method,path)==("POST",f"/resource/leases/{self.lease}/heartbeat"):
            return {"state":"active"}
        raise AssertionError(f"unapproved broker API path {method} {path}")


def setup_broker(monkeypatch):
    api=FakeAPI()
    uid=os.getuid()
    pid=os.getpid()
    broker=vision_rm_broker.ControlBroker(
        gateway="http://127.0.0.1:1",vision_uid=uid,
        runner_path=Path("/root/strict-root-owned-runner.py"),
        runner_sha256="a"*64,
        api_call=api,peer_validator=lambda p,u: p==pid and u==uid)
    monkeypatch.setattr(vision_rm_broker,"worker_cgroup_path",
                        lambda p,expected_uid=None:"/test/trusted/scope" if p==pid and expected_uid==uid else None)
    return broker,api,pid,uid


def test_broker_does_not_expose_control_bearer_or_arbitrary_gateway_methods(monkeypatch):
    broker,api,pid,uid=setup_broker(monkeypatch)
    assert broker.request({"op":"create"},peer_pid=pid,peer_uid=uid+1)=={"status":"denied"}
    assert not api.calls
    created=broker.request({"op":"create"},peer_pid=pid,peer_uid=uid)
    assert created["status"]=="ok"
    assert "lease_id" not in created and "token" not in created
    sid=created["session"]
    assert broker.request({"op":"create"},peer_pid=pid,peer_uid=uid)=={"status":"busy"}
    assert broker.request({"op":"POST","path":"/resource/leases"},peer_pid=pid,peer_uid=uid)=={"status":"denied"}
    assert broker.request({"op":"poll","session":"wrong"},peer_pid=pid,peer_uid=uid)=={"status":"denied"}
    assert broker.request({"op":"poll","session":sid},peer_pid=pid,peer_uid=uid)=={"status":"ok","state":"active"}
    bad=broker.request({"op":"begin","session":sid,"worker_pid":pid,"scope_path":"/wrong"},
                       peer_pid=pid,peer_uid=uid)
    assert bad["status"]=="worker_scope_denied"
    admitted=broker.request({"op":"begin","session":sid,"worker_pid":pid,
                             "scope_path":"/test/trusted/scope"},peer_pid=pid,peer_uid=uid)
    assert admitted["status"]=="ok"
    cap=admitted["authorization"]
    assert set(cap)=={"lease_id","use_id","worker_token"}
    assert len(cap["worker_token"])>32
    assert broker.request({"op":"begin","session":sid,"worker_pid":pid,
                           "scope_path":"/test/trusted/scope"},peer_pid=pid,peer_uid=uid)["status"]=="already_started"
    assert broker.request({"op":"finish","session":sid},peer_pid=pid,peer_uid=uid)=={"status":"released"}
    assert broker.session is None
    assert broker.request({"op":"finish","session":sid},peer_pid=pid,peer_uid=uid)=={"status":"denied"}


def test_socket_protocol_uses_credentialled_peer_identity(monkeypatch):
    broker,api,pid,uid=setup_broker(monkeypatch)
    with tempfile.TemporaryDirectory() as d:
        sock=Path(d)/"broker.sock"
        stop=threading.Event()
        thread=threading.Thread(target=vision_rm_broker.serve,kwargs={
            "broker":broker,"socket_path":sock,"stop_event":stop},daemon=True)
        thread.start()
        deadline=time.monotonic()+3
        while not sock.exists():
            assert time.monotonic()<deadline
            time.sleep(.01)
        def call(payload):
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(str(sock))
                client.sendall(json.dumps(payload).encode())
                return json.loads(client.recv(4096))
        assert call({"op":"restart_ollama"})=={"status":"denied"}
        assert not api.calls
        result=call({"op":"create"})
        assert result["status"]=="ok" and "lease_id" not in result
        assert call({"op":"finish","session":result["session"]})=={"status":"released"}
        stop.set()
        thread.join(timeout=4)
        assert not thread.is_alive()


@pytest.mark.anyio
async def test_read_only_use_capability_cannot_mutate_resource_leases(tmp_path):
    prov=Providers()
    app=create_gateway_app(Settings(_env_file=None,gateway_vision_external_enabled=True,
        gateway_vision_executor_token="test-only-secret-controller-kept-outside-model",
        gateway_vision_worker_gate_sha256="a"*64,
        gateway_vision_allowed_scripts={"/dummy/script.py":"a"*64},
        gateway_vision_strict_gpu_clients=False,
        gateway_gpu_marker=tmp_path/"dev-recovery"),
        upstream_transport=httpx.MockTransport(prov.handle),
        residency_transport=httpx.MockTransport(prov.handle))
    async with api_client(app) as client:
        app.state.resource_leases.vision_attestation=lambda pid:True
        state={"birth":123}
        res=app.state.resource_leases.residency
        res.vision_process_probe=lambda pid:state["birth"]
        res.vision_scope_probe=lambda pid:"fake-scope"
        res.vision_cgroup_members=lambda scope:({222} if state["birth"] else set())
        res.vision_memory_probe=lambda:1024
        client.headers["x-ai-vision-executor-token"]="test-only-secret-controller-kept-outside-model"
        lease=(await client.post("/resource/leases",json={
            "workload":"vision-benchmark","priority_class":"background"})).json()
        lid=lease["lease_id"]
        reply=await client.post(f"/resource/leases/{lid}/uses",json={
            "provider":"vision-local","capability":"image-analysis",
            "worker_pid":222,"scope_path":"fake-scope"})
        assert reply.status_code==201,reply.text
        use=reply.json()
        token=use["worker_token"]
        worker_headers={"x-ai-vision-use-token":token}
        client.headers.pop("x-ai-vision-executor-token",None)
        target=f"/resource/leases/{lid}/uses/{use['use_id']}"
        assert (await client.get(target,headers=worker_headers)).status_code==200
        assert (await client.get(target,headers={"x-ai-vision-use-token":"invalid"})).status_code==409
        assert (await client.get(target)).status_code==403
        assert (await client.post("/resource/leases",json={
            "workload":"vision-benchmark"},headers=worker_headers)).status_code==403
        assert (await client.post(f"/resource/leases/{lid}/heartbeat",headers=worker_headers)).status_code==403
        assert (await client.delete(target,headers=worker_headers)).status_code==403
        assert (await client.delete(f"/resource/leases/{lid}",headers=worker_headers)).status_code==403
        client.headers["x-ai-vision-executor-token"]="test-only-secret-controller-kept-outside-model"
        state["birth"]=None
        assert (await client.delete(target)).status_code==200
        assert (await client.get(target,headers=worker_headers)).status_code==409
        assert (await client.delete(f"/resource/leases/{lid}")).status_code==200
