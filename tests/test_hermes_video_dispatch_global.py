from pathlib import Path
import importlib.util,json,os,sys
ROOT=Path(__file__).resolve().parents[1];LOCAL=ROOT/"tools/local_video";sys.path.insert(0,str(LOCAL));sys.path.insert(0,str(ROOT/"tools"));spec=importlib.util.spec_from_file_location("video_global",LOCAL/"hermes_video_dispatch_global.py");assert spec and spec.loader;mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def test_ack_removes_stage30(monkeypatch):
    monkeypatch.setattr(mod.stage30,"queue_job",lambda parts:"🎬 Stage30: old");monkeypatch.setattr(mod.stage30,"parse_request_args",lambda parts:{"hq":False,"duration_seconds":2});reply=mod.queue_job(["robot","macha"]);assert reply=="🎬 Przyjęto zlecenie filmu: standard 640×384, 2 s. Gotowy film wyślę tutaj.";assert "Stage30" not in reply
def test_worker_holds_and_releases_global_lease(monkeypatch,tmp_path):
    req=tmp_path/"request.json";req.write_text(json.dumps({"target":"telegram:123","prompt":"x"}),encoding="utf-8")
    class Lease:
        lease_id="lease-Y";released=False
        def release(self):self.released=True
    lease=Lease();monkeypatch.setattr(mod.resource,"acquire_resource",lambda **kwargs:lease);monkeypatch.setattr(mod.stage30,"run_worker",lambda path:0);monkeypatch.setattr(mod._LeaseHeaders,"__enter__",lambda self:self);monkeypatch.setattr(mod._LeaseHeaders,"__exit__",lambda self,*exc:None);assert mod.run_worker(req)==0;assert lease.released is True;assert "HERMES_RESOURCE_LEASE_ID" not in os.environ
