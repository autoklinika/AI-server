"""Actual Hermes /foto worker -> existing DEV Gateway RM (HTTP), no Telegram/GPU.

The exact repo Hermes dispatcher and RM helper match production SHA256 on the
AI Platform. DEV changes only local process bindings: a separate loopback
Gateway on 11656, simulated Comfy process behind the existing RM, neutral
prompt fixture and a real previously GPU-generated image as the output fixture.
No production service, Telegram recipient or live renderer is ever accessed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request

import httpx
import pytest
import uvicorn

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_rm_comfy_ondemand_dev import Controller, MockServices

ROOT=Path(__file__).resolve().parents[1]
FOTO_SOURCE=ROOT/"tools/local_image/hermes_foto_dispatch_global.py"
HELPER_SOURCE=ROOT/"tools/hermes_resource_queue.py"
DEV_PORT=11656
URL=f"http://127.0.0.1:{DEV_PORT}"
REAL_VAE_PNG=Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/output/rm-comfy-dev-flux2-vae_00001_.png")
REAL_VAE_SHA="16e0117ddd83e8d051956f3e70cfccf1e9ac81e091f19527383b13fe0d44f205"


def http_api(path,method="GET",body=None):
    raw=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(
        URL+path, data=raw, method=method,
        headers={"Content-Type":"application/json"} if raw else {})
    with urllib.request.urlopen(req,timeout=4) as resp:
        return json.load(resp)


@pytest.fixture
def dev_http_gateway(tmp_path):
    # Refuse occupied loopback ports; NEVER share or replace production :11435.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(1)
        assert s.connect_ex(("127.0.0.1",DEV_PORT))!=0,"DEV test port already allocated"
    controller=Controller()
    service=MockServices(controller)
    settings=Settings(
        _env_file=None,
        gateway_host="127.0.0.1",
        gateway_port=DEV_PORT,
        gateway_comfy_url="http://127.0.0.1:11657",
        ollama_url="http://mocked-dev-only.invalid",
        gateway_gpu_marker=tmp_path/"hermes-rm-recovery.blocked",
        gateway_gpu_transition_timeout=.3,
        gateway_comfy_ondemand_dev_mode=True,
        gateway_max_concurrency=1,
        gateway_vision_radio_enabled=False,
    )
    app=create_gateway_app(settings,
        upstream_transport=httpx.MockTransport(service.ollama),
        residency_transport=httpx.MockTransport(service.comfy),
        comfy_process_controller=controller)
    config=uvicorn.Config(app,host="127.0.0.1",port=DEV_PORT,
                         log_level="error",access_log=False,
                         lifespan="on",loop="asyncio")
    server=uvicorn.Server(config)
    thread=threading.Thread(target=server.run,name="dev-hermes-rm-local-gateway",daemon=True)
    thread.start()
    start=time.monotonic()
    while not server.started:
        assert thread.is_alive(),"DEV isolated ASGI Gateway startup failed"
        assert time.monotonic()-start<8,"DEV isolated ASGI Gateway startup timeout"
        time.sleep(.05)
    controller.residency=app.state.resource_leases.residency
    try:
        snapshot=http_api("/health")
        assert snapshot["status"]=="ok"
        assert snapshot["resource_manager"]["state"]=="IDLE"
        assert snapshot["scheduler"]["active_count"]==0
        assert snapshot["scheduler"]["queued_count"]==0
        assert not controller.active
        yield controller,service,app,tmp_path
    finally:
        server.should_exit=True
        thread.join(timeout=8)
        assert not thread.is_alive(),"DEV isolated ASGI Gateway did not terminate"


@pytest.fixture
def hermes_worker_dev(monkeypatch,tmp_path):
    # Load the actual repo Hermes worker+helper as separate module copies;
    # never edit /usr/local or the real Hermes service.
    spec=importlib.util.spec_from_file_location(
        "hermes_foto_rm_ondemand_e2e_dev_worker",FOTO_SOURCE)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    assert module.base.__file__.endswith("tools/local_image/hermes_foto_dispatch.py")
    assert module.resource.__file__.endswith("tools/hermes_resource_queue.py")

    # The installed helper intentionally permits ONLY prod :11435. Override
    # the connection just inside this imported DEV module to our isolated
    # ASGI localhost. No production configuration or code is changed.
    monkeypatch.setattr(module.resource,"_gateway",lambda:URL)
    monkeypatch.setattr(module.resource,"_float_env",
        lambda name,default,low,high: .1 if "POLL" in name else (0.0 if "NOTICE" in name else 2.0))
    notifications=[]
    deliveries=[]
    monkeypatch.setattr(module.resource,"_notify",
        lambda target,message: notifications.append((target,message)))
    monkeypatch.setattr(module.base,"_send",
        lambda target,message,**kwargs: deliveries.append((target,message)))
    monkeypatch.setattr(module.base,"compile_image_prompt",
        lambda original,has_input: {
            "qwen_used":True,
            "intent":"edit" if has_input else "generate",
            "prompt":"A workshop oscilloscope on a clean bench, natural lighting.",
            "failure_reason":None,
            "elapsed_seconds":0.001,
        })
    monkeypatch.delenv("HERMES_RESOURCE_LEASE_ID",raising=False)
    monkeypatch.delenv("HERMES_RESOURCE_USE_ID",raising=False)
    monkeypatch.setenv("HERMES_MEDIA_RESOURCE_PRIORITY","50")
    return module,notifications,deliveries


def create_job(root,prompt="Oscyloskop na stole warsztatowym",has_image=False):
    job=root/"hermes-job"
    job.mkdir()
    original=job/"input.png"
    if has_image:
        original.write_bytes(b"DEV-image-file-no-physical-GPU")
    (job/"request.json").write_text(json.dumps({
        "job_id":"DEV-only-RM-test",
        "prompt":prompt,
        "target":"telegram:DEV_UNROUTABLE_NO_SEND",
        "input_image":str(original) if has_image else None,
        "mode":"edit" if has_image else "generate",
    },ensure_ascii=False),encoding="utf-8")
    return job


def image_evidence(root):
    if REAL_VAE_PNG.is_file():
        image=REAL_VAE_PNG
        assert sha256(image.read_bytes()).hexdigest()==REAL_VAE_SHA
        return image,"previous_real_AMD_ROCM_VAE_output"
    # In GitHub CI, the private host evidence is absent. This tests contract
    # only; the artifact is never claimed to have been rendered by a GPU.
    image=root/"dev_contract_only.png"
    image.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
    ))
    return image,"CI_contract_only_fixture"


def test_hermes_worker_uses_real_http_dev_rm_and_keeps_other_job_queued(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    controller,service,_,_=dev_http_gateway
    hermes,notifications,deliveries=hermes_worker_dev
    artifact,kind=image_evidence(tmp_path)
    job=create_job(tmp_path)
    helper=hermes.resource
    seen=[]
    original=helper._json

    def read_through(method,path,payload=None,timeout=5.0):
        assert helper._gateway()==URL,"DEV helper accidentally points to production"
        seen.append((method,path,payload))
        return original(method,path,payload,timeout)

    monkeypatch.setattr(helper,"_json",read_through)
    added={}
    def isolated_generator(req,log):
        assert req["prompt"].startswith("A workshop oscilloscope")
        lease=os.environ.get("HERMES_RESOURCE_LEASE_ID")
        use=os.environ.get("HERMES_RESOURCE_USE_ID")
        assert lease and use
        assert helper._json("GET",f"/resource/leases/{lease}/uses/{use}")=={
            "provider":"comfyui-local","capability":"image-generation"}
        assert controller.active and controller.residency.state=="media"
        assert controller.residency.marker.is_file()
        snapshot=http_api("/status")
        assert snapshot["active_count"]==1 and snapshot["queued_count"]==0
        # Exercise the existing RM queue WHILE Hermes is still using ComfyUI.
        nextjob=helper._json("POST","/resource/leases",{
            "source":"queued-diagnostic-job","priority":100,"workload":"media-image"})
        assert nextjob["state"]=="queued"
        added["id"]=nextjob["lease_id"]
        snapshot=http_api("/status")
        assert snapshot["active_count"]==1 and snapshot["queued_count"]==1
        log.write("[DEV_NO_REAL_RENDER] returned prior AMD VAE image fixture\n")
        return artifact

    monkeypatch.setattr(hermes,"_original_generator",isolated_generator)
    assert hermes.worker(job)==0
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is True and result["mode"]=="generate"
    assert result["qwen_used"] is True
    assert result["path"]==str(artifact)
    assert deliveries==[("telegram:DEV_UNROUTABLE_NO_SEND",f"MEDIA:{artifact}")]
    assert notifications==[]
    assert controller.events==["start","stop"]
    assert controller.residency.state=="llm"
    assert not controller.residency.marker.exists()
    assert service.events.count(("comfy","/free"))>=1
    assert any(path=="/resource/leases" and payload.get("source")=="telegram-foto"
               for method,path,payload in seen if method=="POST" and payload)
    assert any(method=="POST" and path.endswith("/uses") for method,path,_ in seen)
    assert any(method=="DELETE" and "/uses/" in path for method,path,_ in seen)
    assert "HERMES_RESOURCE_LEASE_ID" not in os.environ
    assert "HERMES_RESOURCE_USE_ID" not in os.environ
    assert helper._json("GET","/resource/leases/"+added["id"])["state"]=="active"
    assert helper._json("DELETE","/resource/leases/"+added["id"])["released"]
    status=http_api("/status")
    assert status["active_count"]==status["queued_count"]==0
    # Artifact provenance is preserved, never a claim that this test rendered it.
    if kind=="previous_real_AMD_ROCM_VAE_output":
        assert sha256(artifact.read_bytes()).hexdigest()==REAL_VAE_SHA


def test_hermes_queued_notices_never_contact_telegram(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    controller,_,_,_=dev_http_gateway
    hermes,notifications,deliveries=hermes_worker_dev
    source,kind=image_evidence(tmp_path)
    job=create_job(tmp_path)
    worker_called=[]
    def fake_render(request,log):
        worker_called.append("after_real_rm_grant")
        assert controller.active
        return source

    monkeypatch.setattr(hermes,"_original_generator",fake_render)
    blocker=hermes.resource.acquire_resource(
        target=None,source="pre-existing-dev-workload",
        priority=10,workload="media-image")
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            task=pool.submit(hermes.worker,job)
            start=time.monotonic()
            while time.monotonic()-start<4:
                stat=http_api("/status")
                if stat["active_count"]==1 and stat["queued_count"]==1:
                    break
                time.sleep(.03)
            else:
                raise AssertionError("Hermes was not queued behind existing RM work")
            assert worker_called==[]
            assert task.done() is False
            blocker.release()
            assert task.result(timeout=5)==0
    finally:
        blocker.release()
    assert worker_called==["after_real_rm_grant"]
    assert controller.events==["start","stop"]
    assert len(notifications)==2
    assert notifications[0][0]==notifications[1][0]=="telegram:DEV_UNROUTABLE_NO_SEND"
    assert "czeka" in notifications[0][1].lower()
    assert "rozpoczynam" in notifications[1][1].lower()
    assert len(deliveries)==1 and deliveries[0][1].startswith("MEDIA:")
    assert http_api("/status")["active_count"]==0
    assert http_api("/status")["queued_count"]==0
    assert controller.residency.marker.exists() is False


def test_hermes_qwen_rejection_causes_no_comfy_start(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    controller,_,_,_=dev_http_gateway
    hermes,_,deliveries=hermes_worker_dev
    job=create_job(tmp_path)
    monkeypatch.setattr(hermes.base,"compile_image_prompt",
        lambda prompt,has_image:{
            "qwen_used":False,"intent":"unknown","prompt":prompt,
            "failure_reason":"DEV simulated unavailable prompt compiler",
            "elapsed_seconds":0.002,
        })
    def forbidden_render(request,log):
        raise AssertionError("no renderer may be called without Qwen acceptance")
    monkeypatch.setattr(hermes,"_original_generator",forbidden_render)
    assert hermes.worker(job)==1
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is False and result["qwen_used"] is False
    assert len(deliveries)==1 and "nie powiodło" in deliveries[0][1]
    assert not controller.active and controller.events==[]
    assert controller.residency.state=="llm"
    assert not controller.residency.marker.exists()
    assert http_api("/status")["active_count"]==0


def test_hermes_generator_exception_still_stops_dev_comfy_and_unpins(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    controller,_,_,_=dev_http_gateway
    hermes,_,deliveries=hermes_worker_dev
    job=create_job(tmp_path)

    def broken_generator(request,log):
        assert controller.active and controller.residency.state=="media"
        assert os.environ.get("HERMES_RESOURCE_USE_ID")
        raise RuntimeError("DEV renderer exception, no production GPU involved")

    monkeypatch.setattr(hermes,"_original_generator",broken_generator)
    assert hermes.worker(job)==1
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is False
    assert "DEV renderer exception" in result["error"]
    assert len(deliveries)==1 and "nie powiodło" in deliveries[0][1]
    assert controller.events==["start","stop"]
    assert controller.active is False
    assert controller.residency.state=="llm"
    assert not controller.residency.marker.exists()
    assert http_api("/status")["active_count"]==0
    assert http_api("/status")["queued_count"]==0


def test_failed_comfy_cleanup_keeps_slot_marker_and_hermes_reports_error(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    controller,service,_,_=dev_http_gateway
    hermes,_,deliveries=hermes_worker_dev
    job=create_job(tmp_path)
    image,_=image_evidence(tmp_path)
    service.cleanup_failed=True

    def finish_without_cleaning(request,log):
        assert controller.active
        assert os.environ.get("HERMES_RESOURCE_USE_ID")
        return image

    monkeypatch.setattr(hermes,"_original_generator",finish_without_cleaning)
    assert hermes.worker(job)==1
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is False
    assert "media cleanup failed" in result["error"]
    assert len(deliveries)==1
    assert "nie powiodło" in deliveries[0][1]
    assert controller.events==["start"]
    assert controller.active is True,"Failed cleanup must not claim engine stopped"
    assert controller.residency.marker.exists()
    s=http_api("/status")
    assert s["admission_blocked"] is True
    assert s["gpu_residency"]["recovery_required"] is True
    assert s["active_count"]==1
    assert s["resource_leases"]["lease_count"]==1
    assert (http_api("/health"))["status"]=="degraded"
    assert "HERMES_RESOURCE_LEASE_ID" not in os.environ
    assert "HERMES_RESOURCE_USE_ID" not in os.environ
    # The fake controller is only a test double; no physical process remains.


def test_hermes_image_edit_capability_routes_to_same_existing_rm(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    controller,_,_,_=dev_http_gateway
    hermes,_,deliveries=hermes_worker_dev
    job=create_job(tmp_path,has_image=True)
    image,_=image_evidence(tmp_path)
    observed={}

    def simulate_renderer(request,log):
        assert request["input_image"]
        lease=os.environ["HERMES_RESOURCE_LEASE_ID"]
        use=os.environ["HERMES_RESOURCE_USE_ID"]
        observed["capability"]=hermes.resource._json(
            "GET",f"/resource/leases/{lease}/uses/{use}")["capability"]
        assert observed["capability"]=="image-edit"
        assert controller.residency.state=="media"
        return image

    monkeypatch.setattr(hermes,"_original_generator",simulate_renderer)
    assert hermes.worker(job)==0
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is True and result["mode"]=="edit"
    assert observed["capability"]=="image-edit"
    assert len(deliveries)==1 and deliveries[0][1].startswith("MEDIA:")
    assert controller.events==["start","stop"]
    assert not controller.residency.marker.exists()
    assert http_api("/status")["active_count"]==0


def test_production_executables_match_repo_source_on_authorized_host():
    # On CI, original production files are not mounted; this is an additional
    # integrity assertion whenever running on the real AI Platform.
    originals=(
        (Path("/usr/local/bin/hermes-foto-dispatch"),FOTO_SOURCE),
        (Path("/usr/local/libexec/ai-server/hermes_resource_queue.py"),HELPER_SOURCE),
        (Path("/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py"),
         ROOT/"tools/local_image/hermes_foto_prompt_compiler.py"),
        (Path("/opt/ai-platform/current/services/ai-bridge/src/ai_bridge/providers/media_admission.py"),
         ROOT/"src/ai_bridge/providers/media_admission.py"),
    )
    if not all(first.exists() for first,_ in originals):
        pytest.skip("production source installed only on authorized AI Platform")
    for deployed,committed in originals:
        assert sha256(deployed.read_bytes()).digest()==sha256(committed.read_bytes()).digest()


def test_no_real_telegram_or_prod_gpu_calls_in_dev_harness():
    source=Path(__file__).read_text()
    for token in (
        'target":"telegram:DEV_UNROUTABLE_NO_SEND"',
        'monkeypatch.setattr(module.base,"_send"',
        'monkeypatch.setattr(module.resource,"_notify"',
        'monkeypatch.setattr(module.resource,"_gateway",lambda:URL)',
        'gateway_comfy_url="http://127.0.0.1:11657"',
        'ollama_url="http://mocked-dev-only.invalid"',
        'httpx.MockTransport(service.comfy)',
    ):
        assert token in source
    assert URL=="http://127.0.0.1:11656"
    assert DEV_PORT!=11435


def test_real_renderer_admission_checks_hermes_lease_and_use_tokens(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    from types import SimpleNamespace
    from ai_bridge.providers import media_admission

    controller,_,_,_=dev_http_gateway
    hermes,_,delivered=hermes_worker_dev
    image,_=image_evidence(tmp_path)
    job=create_job(tmp_path)
    redirects=[]

    class RedirectOnlyLegacyRenderGate:
        """Intercept the frozen legacy generator client INSIDE this test.

        The production renderer has a fixed port 11435. This proxy makes a
        strict test-only translation of that exact constructor to DEV 11656.
        No HTTP request is allowed to reach production through this object.
        """
        def __init__(self,*,base_url,timeout=5,trust_env=False,**kwargs):
            assert base_url=="http://127.0.0.1:11435"
            assert trust_env is False
            redirects.append((base_url,URL))
            self.client=httpx.Client(base_url=URL,timeout=timeout,trust_env=False)
        def __enter__(self):
            self.client.__enter__()
            return self.client
        def __exit__(self,*exc):
            return self.client.__exit__(*exc)

    # Change the provider module binding, NOT the installed renderer code and
    # NOT the shared httpx.Client class used by other apps/services.
    monkeypatch.setattr(media_admission,"httpx",
                        SimpleNamespace(Client=RedirectOnlyLegacyRenderGate))

    def renderer(request,log):
        assert controller.active and controller.residency.state=="media"
        assert os.environ.get("HERMES_RESOURCE_LEASE_ID")
        assert os.environ.get("HERMES_RESOURCE_USE_ID")
        # This is the actual ai_bridge.providers.media_admission guard
        # currently imported by the installed generate_image.py code.
        media_admission.require_external_media_use("image-generation")
        # A missing token must be refused before it touches HTTP.
        original_use=os.environ.pop("HERMES_RESOURCE_USE_ID")
        try:
            with pytest.raises(media_admission.MediaAdmissionError):
                media_admission.require_external_media_use("image-generation")
        finally:
            os.environ["HERMES_RESOURCE_USE_ID"]=original_use
        # A wrong media capability is not authorized by the valid tokens.
        with pytest.raises(media_admission.MediaAdmissionError):
            media_admission.require_external_media_use("image-edit")
        assert len(redirects)==2
        return image

    monkeypatch.setattr(hermes,"_original_generator",renderer)
    assert hermes.worker(job)==0
    assert controller.events==["start","stop"]
    assert controller.residency.state=="llm"
    assert not controller.residency.marker.exists()
    assert len(delivered)==1 and delivered[0][1].startswith("MEDIA:")
    assert len(redirects)==2
    assert http_api("/status")["active_count"]==0
    assert http_api("/status")["queued_count"]==0


def test_hermes_edit_intent_without_source_never_reaches_gpu(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    ctl,_,_,_=dev_http_gateway
    hermes,_,deliveries=hermes_worker_dev
    job=create_job(tmp_path,prompt="Zmień kolor tego przedmiotu na zielony")
    monkeypatch.setattr(hermes.base,"compile_image_prompt",
        lambda original,has_image: {
            "qwen_used":True,"intent":"edit",
            "prompt":"Change only the object color to green.",
            "failure_reason":None,"elapsed_seconds":0.001,
        })
    def forbid_generator(req,log):
        raise AssertionError("missing image must not cause model execution")
    monkeypatch.setattr(hermes,"_original_generator",forbid_generator)
    assert hermes.worker(job)==3
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is False and result["needs_input_image"] is True
    assert "edit_without_input_image" in (job/"worker.log").read_text()
    assert len(deliveries)==1
    assert "zdjęcia" in deliveries[0][1].lower()
    assert not ctl.active and ctl.events==[]
    assert not ctl.residency.marker.exists()
    assert http_api("/status")["active_count"]==0


def test_hermes_cannot_bypass_failed_dev_comfy_start(
    dev_http_gateway,hermes_worker_dev,tmp_path,monkeypatch
):
    ctl,_,_,_=dev_http_gateway
    hermes,_,deliveries=hermes_worker_dev
    ctl.fail_start=True
    job=create_job(tmp_path)
    def forbid_generator(req,log):
        raise AssertionError("failed ComfyUI must not start renderer")
    monkeypatch.setattr(hermes,"_original_generator",forbid_generator)
    assert hermes.worker(job)==1
    result=json.loads((job/"result.json").read_text())
    assert result["ok"] is False and len(deliveries)==1
    assert ctl.events==["start"]
    assert not ctl.active
    assert ctl.residency.marker.exists()
    state=http_api("/status")
    assert state["admission_blocked"] is True
    assert state["gpu_residency"]["recovery_required"] is True
    assert state["active_count"]==1
    assert state["resource_leases"]["lease_count"]==1
    assert http_api("/health")["status"]=="degraded"
