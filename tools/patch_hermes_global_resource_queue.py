#!/usr/bin/env python3
from __future__ import annotations
import argparse,os,tempfile
from pathlib import Path
MARKER="AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1";ANCHOR="    # Private to the in-process MoA facade; added after middleware/hooks/debug dumps so";EXPECTED_BUILD="def build_api_request(";EXPECTED_HEADER_HELPER="def _set_extra_header("
class PatchError(RuntimeError):pass

def _block()->str:
    return '''    # AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1: global slot for Telegram LLM calls.\n    try:\n        _rq_platform = str(getattr(agent, "platform", "") or "").strip().lower()\n        _rq_chat = str(getattr(agent, "_chat_id", "") or "").strip()\n        if _rq_platform == "telegram" and _rq_chat:\n            import importlib.util as _rq_importlib\n            import os as _rq_os\n            import sys as _rq_sys\n            _rq_name = "_ai_server_resource_queue"\n            _rq_mod = _rq_sys.modules.get(_rq_name)\n            if _rq_mod is None:\n                _rq_path = _rq_os.environ.get("HERMES_RESOURCE_HELPER", "/usr/local/libexec/ai-server/hermes_resource_queue.py")\n                _rq_spec = _rq_importlib.spec_from_file_location(_rq_name, _rq_path)\n                if _rq_spec is None or _rq_spec.loader is None:\n                    raise RuntimeError("global resource helper unavailable")\n                _rq_mod = _rq_importlib.module_from_spec(_rq_spec)\n                _rq_sys.modules[_rq_name] = _rq_mod\n                _rq_spec.loader.exec_module(_rq_mod)\n            if _rq_mod.should_manage_base_url(str(getattr(agent, "base_url", "") or "")):\n                _rq_thread = str(getattr(agent, "_thread_id", "") or "").strip()\n                _rq_target = "telegram:" + _rq_chat + ((":" + _rq_thread) if _rq_thread else "")\n                _rq_lease = _rq_mod.acquire_resource(target=_rq_target, source="telegram-chat", priority=50, queue_message=("⏳ Twoje zapytanie czeka w kolejce. Powiadomię Cię, gdy rozpocznie się przetwarzanie."), start_message="▶️ Zwolniły się zasoby. Rozpoczynam Twoje zapytanie.")\n                _set_extra_header(api_kwargs, "X-AI-Resource-Lease", _rq_lease.lease_id)\n                _set_extra_header(api_kwargs, "X-AI-Resource-Lease-Release", "1")\n    except Exception as _rq_exc:\n        logger.warning("Global resource queue unavailable for Telegram request: %s", _rq_exc)\n\n'''

def patch_text(text:str)->str:
    if text.count(MARKER)>1:raise PatchError("duplicate global resource queue marker")
    if MARKER in text:compile(text,"agent/turn_api_request.py","exec");return text
    if EXPECTED_BUILD not in text or EXPECTED_HEADER_HELPER not in text:raise PatchError("unsupported Hermes turn_api_request layout")
    if text.count(ANCHOR)!=1:raise PatchError(f"expected one insertion anchor, found {text.count(ANCHOR)}")
    patched=text.replace(ANCHOR,_block()+ANCHOR,1)
    if patched.count(MARKER)!=1:raise PatchError("marker insertion failed")
    compile(patched,"agent/turn_api_request.py","exec");return patched

def check_text(text:str)->str:
    try:patched=patch_text(text)
    except (PatchError,SyntaxError) as exc:return f"unsupported:{exc}"
    return "patched" if patched==text else "patchable"

def atomic_write(path:Path,text:str)->None:
    st=path.stat();fd,tmp=tempfile.mkstemp(prefix=path.name+".resource.",dir=str(path.parent),text=True)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,st.st_mode)
        try:os.chown(tmp,st.st_uid,st.st_gid)
        except PermissionError:pass
        os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass

def main(argv=None)->int:
    p=argparse.ArgumentParser();p.add_argument("path",type=Path);p.add_argument("--check",action="store_true");a=p.parse_args(argv)
    try:
        text=a.path.read_text(encoding="utf-8")
        if a.check:
            state=check_text(text);print(state);return 0 if state in {"patched","patchable"} else 2
        patched=patch_text(text)
        if patched==text:print("already patched");return 0
        atomic_write(a.path,patched);print("patched");return 0
    except (OSError,PatchError,SyntaxError) as exc:print(f"ERROR: {exc}");return 1
if __name__=="__main__":raise SystemExit(main())
