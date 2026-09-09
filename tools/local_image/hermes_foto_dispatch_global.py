#!/usr/bin/env python3
from __future__ import annotations
import argparse,importlib.util,os,sys,urllib.request
from pathlib import Path
TOOLS_DIR=Path(__file__).resolve().parents[1] if "local_image" in Path(__file__).parts else None
BASE_PROD=Path("/usr/local/libexec/ai-server/hermes_foto_dispatch_base.py");HELPER_PROD=Path("/usr/local/libexec/ai-server/hermes_resource_queue.py")
def _load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:raise RuntimeError(f"Nie można załadować {path}")
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
def _base_path():
    local=Path(__file__).resolve().with_name("hermes_foto_dispatch.py")
    if local.is_file() and local.resolve()!=Path(__file__).resolve():return local
    if BASE_PROD.is_file():return BASE_PROD
    raise RuntimeError("Brak bazowego dispatchera /foto.")
def _helper_path():
    local=(TOOLS_DIR/"hermes_resource_queue.py") if TOOLS_DIR else None
    if local and local.is_file():return local
    if HELPER_PROD.is_file():return HELPER_PROD
    raise RuntimeError("Brak klienta globalnej kolejki.")
base=_load("hermes_foto_dispatch_base_runtime",_base_path());resource=_load("hermes_resource_queue_runtime",_helper_path())
class _LeaseHeaders:
    def __enter__(self):
        self.original=urllib.request.Request;lease_headers=resource.lease_headers_from_env()
        def request(url,data=None,headers=None,*args,**kwargs):
            merged=dict(headers or {})
            if resource.should_manage_base_url(str(url)):merged.update(lease_headers)
            return self.original(url,data,merged,*args,**kwargs)
        urllib.request.Request=request;return self
    def __exit__(self,*exc):urllib.request.Request=self.original
def worker(job_dir:Path)->int:
    request=base.json.loads((job_dir/"request.json").read_text(encoding="utf-8"));target=str(request.get("target") or "")
    lease=resource.acquire_resource(target=target,source="telegram-foto" if target.startswith("telegram:") else "foto",priority=int(os.environ.get("HERMES_MEDIA_RESOURCE_PRIORITY","50")),queue_message="⏳ Obraz czeka w kolejce. Powiadomię Cię, gdy rozpocznie się generowanie.",start_message="▶️ Zwolniły się zasoby. Rozpoczynam generowanie obrazu.")
    old=os.environ.get("HERMES_RESOURCE_LEASE_ID");os.environ["HERMES_RESOURCE_LEASE_ID"]=lease.lease_id
    try:
        with _LeaseHeaders():return base.worker(job_dir)
    finally:
        if old is None:os.environ.pop("HERMES_RESOURCE_LEASE_ID",None)
        else:os.environ["HERMES_RESOURCE_LEASE_ID"]=old
        lease.release()
def dispatch(prompt:str)->str:
    original=base.__file__;base.__file__=__file__
    try:reply=base.dispatch(prompt)
    finally:base.__file__=original
    if str(reply).startswith("Użycie:"):return str(reply)
    if str(os.environ.get("HERMES_FOTO_INPUT_IMAGE") or "").strip():return "🖼️ Przyjęto edycję zdjęcia. Gotowy obraz wyślę tutaj."
    return "🖼️ Przyjęto zlecenie obrazu. Gotowy obraz wyślę tutaj."
def main(argv=None)->int:
    p=argparse.ArgumentParser();p.add_argument("prompt",nargs="*");p.add_argument("--worker",type=Path);p.add_argument("--preflight",action="store_true");a=p.parse_args(argv)
    if a.preflight:
        out=base.preflight();print(base.json.dumps(out,ensure_ascii=False,indent=2));return 0 if out["ok"] else 2
    if a.worker:return worker(a.worker)
    try:print(dispatch(" ".join(a.prompt)));return 0
    except Exception as exc:print(str(exc),file=sys.stderr);return 1
if __name__=="__main__":raise SystemExit(main())
