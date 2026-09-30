#!/usr/bin/env python3
"""Exclusive idle-GPU diagnostic window using existing resource reservations.

No service stop/restart or GPU recovery. New faults retain the reservation and
heartbeat (HOLD_FAULT) to prevent queued inference on a known tainted device.
Operator must resolve containment explicitly; no automatic training continuation.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from mes_stability import kernel_records, count_records, save, boot_id, telemetry, gpu_path, GIB


def api(port, method, path, data=None, timeout=5):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=body,
                                     method=method, headers={'Content-Type':'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def wait_idle_gpu(heartbeat, timeout=30):
    deadline = time.monotonic() + timeout
    consecutive = 0
    while consecutive < 2:
        heartbeat()
        sample = telemetry(gpu_path())
        idle = sample['mem_info_vram_used'] <= 2*GIB and sample['gpu_busy_percent'] <= 5
        consecutive = consecutive + 1 if idle else 0
        if time.monotonic() > deadline:
            raise RuntimeError('GPU physical release/idle timeout')
        time.sleep(1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--variants', nargs='+', choices=['A','B','C','D','E'], default=['A','B','C','D'])
    p.add_argument('--seconds', type=int, default=60)
    p.add_argument('--resident-gib', type=float, default=2)
    p.add_argument('--profile', choices=['synthetic','qwen'], default='synthetic')
    p.add_argument('--repeats', type=int, default=1)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    status=api(11435,'GET','/status')
    if status['active_count'] or status['queued_count'] or status['admission_blocked']:
        raise RuntimeError('platform not idle/ready; no production job interrupted')
    rows=kernel_records()
    if count_records(rows):
        raise RuntimeError('boot already tainted')
    initial_boot=boot_id();cursor=rows[-1]['__CURSOR']
    models=api(11434,'GET','/api/ps')['models']
    save(args.output/'resident-models.json',models)
    lease=api(11435,'POST','/resource/leases',{'source':'p5-mes-diagnostic-window',
               'priority_class':'maintenance','workload':'external'})
    lease_path='/resource/leases/'+lease['lease_id']
    save(args.output/'lease.json',lease)
    child=None; unsafe=False; success=False; unloaded=False
    def heartbeat():
        response=api(11435,'POST',lease_path+'/heartbeat',{})
        if response.get('state')!='active':
            raise RuntimeError('exclusive resource reservation lost')
    try:
        if lease.get('state')!='active':
            raise RuntimeError('reservation not immediately active; retry in idle window')
        heartbeat()
        unloaded=True
        for model in models:
            api(11434,'POST','/api/generate',{'model':model['name'],'keep_alive':0,'stream':False},timeout=30)
        deadline=time.monotonic()+30
        while (api(11434,'GET','/api/ps')['models'] or telemetry(gpu_path())['mem_info_vram_used'] > 2*GIB or telemetry(gpu_path())['gpu_busy_percent'] > 5):
            heartbeat()
            if time.monotonic()>deadline:
                raise RuntimeError('model unload did not complete')
            time.sleep(1)
        for variant in args.variants:
            for repeat in range(args.repeats):
                heartbeat()
                wait_idle_gpu(heartbeat)
                dest=args.output/f'{variant}-{repeat+1}'
                argv=[sys.executable,str(Path(__file__).with_name('mes_stability.py')),'run',
                      '--variant',variant,'--seconds',str(args.seconds),'--resident-gib',str(args.resident_gib),
                      '--profile',args.profile,'--output',str(dest)]
                with (args.output/f'{variant}-{repeat+1}-runner.log').open('w') as log:
                    child=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
                    while child.poll() is None:
                        heartbeat();time.sleep(2)
                child=None
                result=json.loads((dest/'result.json').read_text())
                save(args.output/'progress.json',{'variant':variant,'repeat':repeat+1,'result':result})
                if result['status'] in ('FAIL_CONTAINMENT', 'FAIL_CLEANUP'):
                    unsafe=True
                if result['status']!='PASS_RUN_ONLY':
                    raise RuntimeError('run not passed; matrix stopped')
        success=True
        save(args.output/'matrix.json',{'status':'COMPLETE_RUNS_ONLY','gate':'NOT_AUTOMATICALLY_PASSED'})
    except BaseException as error:
        save(args.output/'matrix.json',{'status':'STOPPED','reason':str(error)})
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:unsafe=True
    finally:
        try:
            unsafe = unsafe or boot_id()!=initial_boot or bool(count_records(kernel_records(cursor=cursor)))
        except Exception:
            unsafe=True
        if unsafe:
            save(args.output/'containment.json',{'status':'HOLD_FAULT','reason':'kernel fault or lost monitoring; no reload/reset/reboot', 'lease_path':lease_path})
            while boot_id()==initial_boot:
                heartbeat();time.sleep(5)
            success=False
        # Restore idle residency exactly by model name and observed context length.
        # An empty generate call loads weights without generating a response.
        try:
            for model in (models if unloaded and not unsafe else []):
                heartbeat()
                api(11434,'POST','/api/generate',{'model':model['name'],'keep_alive':-1,'stream':False,
                    'options':{'num_ctx':model.get('context_length',65536)}},timeout=30)
            if not unsafe:
                save(args.output/'restored-models.json',api(11434,'GET','/api/ps'))
        finally:
            if not unsafe:
                try:
                    unsafe=bool(count_records(kernel_records(cursor=cursor)))
                except Exception:
                    unsafe=True
                if unsafe:
                    save(args.output/'containment.json',{'status':'HOLD_FAULT','reason':'fault/monitor loss during residency restoration','lease_path':lease_path})
                    while boot_id()==initial_boot:
                        heartbeat();time.sleep(5)
                else:
                    api(11435,'DELETE',lease_path)
    return 0 if success else 1

if __name__=='__main__':
    raise SystemExit(main())
