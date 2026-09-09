#!/usr/bin/env python3
from __future__ import annotations
import json,os,shutil,subprocess,threading,time,urllib.error,urllib.parse,urllib.request
from dataclasses import dataclass
GATEWAY_DEFAULT="http://127.0.0.1:11435";QUEUE_NOTICE_AFTER_DEFAULT=0.75;POLL_SECONDS_DEFAULT=0.35;HEARTBEAT_SECONDS_DEFAULT=10.0
class ResourceQueueError(RuntimeError):pass

def should_manage_base_url(base_url:str)->bool:
    try:
        p=urllib.parse.urlparse(str(base_url or ""));return p.scheme in {"http","https"} and (p.hostname or "").lower() in {"127.0.0.1","localhost","::1"} and p.port==11435
    except Exception:return False

def _gateway()->str:
    raw=os.environ.get("HERMES_RESOURCE_GATEWAY_URL",GATEWAY_DEFAULT).strip().rstrip("/")
    if not should_manage_base_url(raw):raise ResourceQueueError("Global Resource Manager musi działać na lokalnym AI Gateway :11435.")
    return raw

def _json(method:str,path:str,payload:dict|None=None,timeout:float=5.0)->dict:
    data=None;headers={"Accept":"application/json"}
    if payload is not None:data=json.dumps(payload).encode("utf-8");headers["Content-Type"]="application/json"
    req=urllib.request.Request(_gateway()+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:raw=r.read()
    except urllib.error.HTTPError as exc:
        body=exc.read().decode("utf-8",errors="replace");raise ResourceQueueError(f"Resource Manager HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:raise ResourceQueueError(f"Resource Manager niedostępny: {getattr(exc,'reason',exc)}") from exc
    value=json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(value,dict):raise ResourceQueueError("Resource Manager zwrócił niepoprawny format.")
    return value

def _hermes_bin()->str:
    configured=os.environ.get("HERMES_CLI_BIN","").strip();candidates=[configured,shutil.which("hermes") or "","/srv/ai-data/hermes/hermes-agent/venv/bin/hermes","/srv/ai-data/hermes/hermes-agent/venv/bin/hermes-agent"]
    for item in candidates:
        if item and os.path.isfile(item) and os.access(item,os.X_OK):return item
    raise ResourceQueueError("Nie znaleziono lokalnego CLI Hermesa do komunikatu Telegram.")

def _notify(target:str|None,message:str|None)->None:
    if not target or not str(target).startswith("telegram:") or not message:return
    proc=subprocess.run([_hermes_bin(),"send","--to",str(target),str(message)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60,check=False)
    if proc.returncode!=0:raise ResourceQueueError("Nie udało się wysłać statusu kolejki Telegram.")

def _float_env(name:str,default:float,lo:float,hi:float)->float:
    try:value=float(os.environ.get(name,default))
    except (TypeError,ValueError):value=default
    return max(lo,min(value,hi))

@dataclass
class ResourceLease:
    lease_id:str;job_id:int;source:str;target:str|None;_stop:threading.Event;_thread:threading.Thread|None=None;_released:bool=False
    def start_heartbeat(self)->None:
        interval=_float_env("HERMES_RESOURCE_HEARTBEAT_SECONDS",HEARTBEAT_SECONDS_DEFAULT,2.0,30.0)
        def run():
            while not self._stop.wait(interval):
                try:_json("POST",f"/resource/leases/{self.lease_id}/heartbeat",timeout=5)
                except Exception:self._stop.set();return
        self._thread=threading.Thread(target=run,name=f"resource-lease-{self.job_id}",daemon=True);self._thread.start()
    def release(self)->None:
        if self._released:return
        self._released=True;self._stop.set()
        try:_json("DELETE",f"/resource/leases/{self.lease_id}",timeout=5)
        except Exception:pass
        if self._thread and self._thread is not threading.current_thread():self._thread.join(timeout=1.0)

def acquire_resource(*,target:str|None,source:str,priority:int=50,queue_message:str|None=None,start_message:str|None=None)->ResourceLease:
    created=_json("POST","/resource/leases",{"source":source,"priority":int(priority)},timeout=5);lease_id=str(created.get("lease_id") or "");job_id=int(created.get("job_id") or 0)
    if not lease_id or job_id<=0:raise ResourceQueueError("Resource Manager nie zwrócił identyfikatora zadania.")
    handle=ResourceLease(lease_id,job_id,source,target,threading.Event());handle.start_heartbeat();state=str(created.get("state") or "");queued_notice=False;started=time.monotonic()
    notice_after=_float_env("HERMES_RESOURCE_QUEUE_NOTICE_AFTER",QUEUE_NOTICE_AFTER_DEFAULT,0.0,5.0);poll=_float_env("HERMES_RESOURCE_POLL_SECONDS",POLL_SECONDS_DEFAULT,0.1,2.0)
    try:
        while state!="active":
            if state!="queued":raise ResourceQueueError(f"Niepoprawny stan Resource Managera: {state or '<pusty>'}")
            if not queued_notice and time.monotonic()-started>=notice_after:
                _notify(target,queue_message);queued_notice=bool(queue_message and target and str(target).startswith("telegram:"))
            time.sleep(poll);status=_json("GET",f"/resource/leases/{lease_id}",timeout=5);state=str(status.get("state") or "")
        if queued_notice:_notify(target,start_message)
        return handle
    except Exception:
        handle.release();raise

def lease_headers_from_env(*,release_after:bool=False)->dict[str,str]:
    lease=os.environ.get("HERMES_RESOURCE_LEASE_ID","").strip()
    if not lease:return {}
    headers={"X-AI-Resource-Lease":lease}
    if release_after:headers["X-AI-Resource-Lease-Release"]="1"
    return headers
