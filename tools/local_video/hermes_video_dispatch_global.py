#!/usr/bin/env python3
from __future__ import annotations
import argparse,os,sys,urllib.request
from pathlib import Path
LOCAL=Path(__file__).resolve().parent
if str(LOCAL) not in sys.path:sys.path.insert(0,str(LOCAL))
if str(LOCAL.parent) not in sys.path:sys.path.insert(0,str(LOCAL.parent))
import hermes_video_dispatch_stage30 as stage30
try:import hermes_resource_queue as resource
except ImportError:
    import importlib.util
    path=Path("/usr/local/libexec/ai-server/hermes_resource_queue.py");spec=importlib.util.spec_from_file_location("hermes_resource_queue",path)
    if spec is None or spec.loader is None:raise
    resource=importlib.util.module_from_spec(spec);sys.modules["hermes_resource_queue"]=resource;spec.loader.exec_module(resource)
class _LeaseHeaders:
    def __enter__(self):
        self.original=urllib.request.Request;lease_headers=resource.lease_headers_from_env()
        def request(url,data=None,headers=None,*args,**kwargs):
            merged=dict(headers or {})
            if resource.should_manage_base_url(str(url)):merged.update(lease_headers)
            return self.original(url,data,merged,*args,**kwargs)
        urllib.request.Request=request;return self
    def __exit__(self,*exc):urllib.request.Request=self.original
def queue_job(parts:list[str])->str:
    parsed=stage30.parse_request_args(parts);original=stage30.__file__;stage30.__file__=__file__
    try:stage30.queue_job(parts)
    finally:stage30.__file__=original
    quality="HQ 1280×768" if parsed["hq"] else "standard 640×384";source=" z obrazu" if str(os.environ.get("HERMES_VIDEO_INPUT_IMAGE") or "").strip() else ""
    return f"🎬 Przyjęto zlecenie filmu: {quality}, {parsed['duration_seconds']} s{source}. Gotowy film wyślę tutaj."
def run_worker(request_path:Path)->int:
    request=stage30.json.loads(request_path.read_text(encoding="utf-8"));target=str(request.get("target") or "")
    lease=resource.acquire_resource(target=target,source="telegram-wideo" if target.startswith("telegram:") else "wideo",priority=int(os.environ.get("HERMES_MEDIA_RESOURCE_PRIORITY","50")),queue_message="⏳ Film czeka w kolejce. Powiadomię Cię, gdy rozpocznie się generowanie.",start_message="▶️ Zwolniły się zasoby. Rozpoczynam generowanie filmu.")
    old=os.environ.get("HERMES_RESOURCE_LEASE_ID");os.environ["HERMES_RESOURCE_LEASE_ID"]=lease.lease_id
    try:
        with _LeaseHeaders():return stage30.run_worker(request_path)
    finally:
        if old is None:os.environ.pop("HERMES_RESOURCE_LEASE_ID",None)
        else:os.environ["HERMES_RESOURCE_LEASE_ID"]=old
        lease.release()
def main(argv=None)->int:
    p=argparse.ArgumentParser(description="Hermes global-queue video dispatcher");p.add_argument("--worker",type=Path);p.add_argument("--qwen-preflight",action="store_true");p.add_argument("parts",nargs="*");a=p.parse_args(argv)
    if a.qwen_preflight:return stage30.qwen_preflight()
    if a.worker:return run_worker(a.worker)
    try:print(queue_job(a.parts),flush=True);return 0
    except (stage30.base.DispatchError,OSError) as exc:print(str(exc),file=sys.stderr,flush=True);return 2
if __name__=="__main__":raise SystemExit(main())
