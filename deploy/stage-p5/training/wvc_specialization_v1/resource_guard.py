#!/usr/bin/env python3
"""Host-side llm reservation supervisor. Never calls the external-use API.

No service transitions; a stopped ComfyUI is allowed only by explicit operator
opt-in and verified UID, state, and systemd cgroup. Lease loss kills training.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request


def request(base,method,path,body=None):
    req=urllib.request.Request(base+path,method=method,
        data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r: return json.load(r)


def check_owners(owners,allow=False,proc=Path('/proc'),uid=None):
    uid=os.getuid() if uid is None else uid
    for pid in owners:
        p=proc/str(pid)
        state=re.search(r'^State:\s+(\w)',(p/'status').read_text(),re.M)
        if not (allow and p.stat().st_uid==uid and state and state[1]=='T'
                and '0::/system.slice/comfyui.service' in (p/'cgroup').read_text().splitlines()):
            raise RuntimeError(f'unexpected_kfd_owner={pid}')


def local_preflight(allow=False):
    # Match the proven P5.11 operator model: lsof inventories current /dev/kfd
    # owners without requiring root. Return codes 0 (owners) and 1 (none)
    # are valid; any other result is fail-closed.
    ollama=subprocess.run(["ollama","ps"],check=True,capture_output=True,text=True).stdout
    if not ollama.splitlines() or not ollama.splitlines()[0].startswith("NAME"):
        raise RuntimeError("unreadable Ollama residency")
    if any(x.strip() for x in ollama.splitlines()[1:]):
        raise RuntimeError("ollama_model_resident")
    inv=subprocess.run(["lsof","-t","/dev/kfd"],capture_output=True,text=True)
    if inv.returncode not in (0,1):
        raise RuntimeError(f"unreadable /dev/kfd owner inventory rc={inv.returncode}")
    owners=sorted({int(x) for x in inv.stdout.split() if x.isdigit()})
    operator_uid=int(os.environ.get("SUDO_UID",os.getuid()))
    check_owners(owners,allow,uid=operator_uid)
    return dict(ollama_ps=ollama,kfd_owners=owners,operator_uid=operator_uid)


def check_manager(status):
    residency=status.get('gpu_residency',{})
    if (status.get('admission_blocked') is not False or residency.get('recovery_required') is not False
            or residency.get('state') not in ('llm','media')):
        raise RuntimeError('Resource Manager admission blocked or status unreadable')


def supervise(base,evidence,command,container,allow=False,api=request,preflight=local_preflight,interval=5,training_manifest=None):
    evidence.mkdir(parents=True,exist_ok=True)
    events=[]; lease=None; child=None; training_rc=None
    def log(kind,**data):
        events.append(dict(event=kind,**data))
        (evidence/'resource_lease.json').write_text(json.dumps(events,indent=2,sort_keys=True)+'\n')
    def stop():
        if child is not None:
            # Even an exited shell could have left a detached Docker workload.
            result=subprocess.run(['docker','rm','-f',container],capture_output=True,text=True)
            log('container_cleanup',returncode=result.returncode)
        if child is not None and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL); child.wait(timeout=10)
    def interrupted(signum,frame): raise RuntimeError(f'interrupted by signal {signum}')
    previous={s:signal.signal(s,interrupted) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
    try:
        log('local_preflight',**preflight(allow))
        status=api(base,'GET','/status'); log('resource_manager_preflight',snapshot=status)
        check_manager(status)
        lease=api(base,'POST','/resource/leases',{'workload':'llm','source':'p513-wvc-training','priority_class':'maintenance'})
        log('reserved',response=lease)
        lease_id=lease.get('lease_id')
        if not lease_id or not re.fullmatch(r'[A-Za-z0-9_-]+',lease_id): raise RuntimeError('invalid lease ID')
        path='/resource/leases/'+lease_id
        if lease.get('state')!='active': raise RuntimeError('training reservation is not active')
        env={**os.environ,'P513_LEASE_ID':lease_id,'P513_LEASE_STATUS':'active','P513_EVIDENCE':str(evidence)}
        # Repeat after admission to close the preflight/reservation interval.
        log('reserved_local_preflight',**preflight(allow))
        child=subprocess.Popen(command,env=env,start_new_session=True)
        while True:
            heartbeat=api(base,'POST',path+'/heartbeat',{})
            log('heartbeat',response=heartbeat)
            check_manager(api(base,'GET','/status'))
            if heartbeat.get('state')!='active' or heartbeat.get('lease_id')!=lease_id:
                raise RuntimeError('lease lost or inactive')
            try:
                training_rc=child.wait(timeout=interval)
                return training_rc
            except subprocess.TimeoutExpired: pass
    except BaseException as exc:
        log('failed',error=str(exc)); raise
    finally:
        try:
            stop()
        finally:
            # Ignore repeat termination during cleanup so DELETE is still attempted.
            for s in previous: signal.signal(s,signal.SIG_IGN)
            try:
                if lease and lease.get('lease_id'):
                    last_error=None
                    for attempt in range(3):
                        try:
                            released=api(base,'DELETE','/resource/leases/'+lease['lease_id'])
                            log('released',response=released)
                            if released.get('released') is not True: raise RuntimeError('lease release not acknowledged')
                            if training_manifest is not None and training_rc==0:
                                manifest=Path(training_manifest)
                                m=json.loads(manifest.read_text())
                                m['lease_status_final']='released'
                                m['lease_evidence_sha256']=__import__('hashlib').sha256((evidence/'resource_lease.json').read_bytes()).hexdigest()
                                manifest.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
                            last_error=None; break
                        except Exception as exc: last_error=exc; log('release_failed',attempt=attempt,error=str(exc))
                    if last_error: raise RuntimeError('lease release failed; inspect evidence') from last_error
            finally:
                for s,handler in previous.items(): signal.signal(s,handler)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--evidence',required=True); ap.add_argument('--container',required=True); ap.add_argument('--training-manifest',required=True)
    ap.add_argument('command',nargs=argparse.REMAINDER); args=ap.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command: ap.error('missing command')
    return supervise(os.environ.get('P513_RESOURCE_URL','http://127.0.0.1:11435'),Path(args.evidence),command,args.container,
                     os.environ.get('P5_ALLOW_QUIESCED_COMFYUI')=='1',training_manifest=args.training_manifest)
if __name__=='__main__': raise SystemExit(main())
