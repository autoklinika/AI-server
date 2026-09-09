from pathlib import Path
import importlib.util,json,os
ROOT=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location("foto_global",ROOT/"tools/local_image/hermes_foto_dispatch_global.py");assert spec and spec.loader;mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def test_ack_is_user_facing_and_has_no_stage_or_qwen(monkeypatch):
    monkeypatch.setattr(mod.base,"dispatch",lambda prompt:"old technical reply");reply=mod.dispatch("czerwony robot");assert reply=="🖼️ Przyjęto zlecenie obrazu. Gotowy obraz wyślę tutaj.";assert "Qwen" not in reply and "Stage" not in reply
def test_worker_holds_and_releases_global_lease(monkeypatch,tmp_path):
    job=tmp_path/"job";job.mkdir();(job/"request.json").write_text(json.dumps({"target":"telegram:123","prompt":"x"}),encoding="utf-8")
    class Lease:
        lease_id="lease-X";released=False
        def release(self):self.released=True
    lease=Lease();monkeypatch.setattr(mod.resource,"acquire_resource",lambda **kwargs:lease);monkeypatch.setattr(mod.base,"worker",lambda path:7);monkeypatch.setattr(mod._LeaseHeaders,"__enter__",lambda self:self);monkeypatch.setattr(mod._LeaseHeaders,"__exit__",lambda self,*exc:None);assert mod.worker(job)==7;assert lease.released is True;assert "HERMES_RESOURCE_LEASE_ID" not in os.environ
