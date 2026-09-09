from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location("hermes_resource_queue_test",ROOT/"tools/hermes_resource_queue.py");assert spec and spec.loader;mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_should_manage_only_local_gateway():
    assert mod.should_manage_base_url("http://127.0.0.1:11435/v1");assert mod.should_manage_base_url("http://localhost:11435/clients/hermes/v1");assert not mod.should_manage_base_url("http://127.0.0.1:11434/v1");assert not mod.should_manage_base_url("https://example.com:11435/v1")

def test_acquire_notifies_only_after_real_queue(monkeypatch):
    states=iter([{"lease_id":"lease-A","job_id":7,"state":"queued"},{"lease_id":"lease-A","job_id":7,"state":"active"}]);notices=[]
    def fake_json(method,path,payload=None,timeout=5):
        if method=="POST" and path=="/resource/leases":return next(states)
        if method=="GET":return next(states)
        if method=="DELETE":return {"released":True}
        if path.endswith("/heartbeat"):return {"state":"queued"}
        raise AssertionError((method,path))
    monkeypatch.setattr(mod,"_json",fake_json);monkeypatch.setattr(mod,"_notify",lambda target,msg:notices.append((target,msg)));monkeypatch.setattr(mod,"_float_env",lambda name,default,lo,hi:0.0 if "NOTICE" in name else (0.001 if "POLL" in name else 30.0));monkeypatch.setattr(mod.ResourceLease,"start_heartbeat",lambda self:None)
    h=mod.acquire_resource(target="telegram:123",source="telegram-chat",queue_message="WAIT",start_message="START");assert notices==[("telegram:123","WAIT"),("telegram:123","START")];h.release()

def test_immediate_slot_sends_no_queue_noise(monkeypatch):
    monkeypatch.setattr(mod,"_json",lambda *a,**k:{"lease_id":"lease-B","job_id":8,"state":"active","released":True});monkeypatch.setattr(mod.ResourceLease,"start_heartbeat",lambda self:None);notices=[];monkeypatch.setattr(mod,"_notify",lambda target,msg:notices.append(msg));h=mod.acquire_resource(target="telegram:123",source="telegram-chat",queue_message="WAIT",start_message="START");assert notices==[];h.release()

def test_non_telegram_target_never_notifies(monkeypatch):
    monkeypatch.setattr(mod,"_json",lambda *a,**k:{"lease_id":"lease-C","job_id":9,"state":"active","released":True});monkeypatch.setattr(mod.ResourceLease,"start_heartbeat",lambda self:None);monkeypatch.setattr(mod,"_notify",lambda *a,**k:(_ for _ in ()).throw(AssertionError("notify")));h=mod.acquire_resource(target=None,source="ventilation");h.release()
