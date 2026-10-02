#!/usr/bin/env python3
"""Root-owned host supervisor; no GPU training is executed by importing this module."""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from prepare_automotive_specialization_v1 import HERE, ROOT, MIX_NAME, SEED, digest, encoded
from validate_automotive_specialization_v1 import check, validate_adapter, validate_dataset

DATA = Path('/srv/ai-data/training/p5')
MODEL = DATA/'models/Qwen3.8-27B-buffered-512m'
PARENT = DATA/'adapters/electronics-foundation-v3/current'
DEST = DATA/'adapters/automotive-specialization-v1'
IMAGE = 'ai-platform-p5-train:rocm7.2.1-v1'
MIN_MEM_KIB = 8 * 1024 * 1024
MAX_IDLE_VRAM = 256 * 1024 * 1024
ERROR = re.compile(
    r'WAIT_REG_MEM|MES.*(?:ring.*full|failed|error|timeout)|'
    r'(?:GPU|amdgpu).*reset|reset.*(?:GPU|amdgpu)|'
    r'(?:KFD|GPUVM|GPU VM|amdgpu|page fault).*(?:error|fault|failed|timeout|hang)|'
    r'(?:error|fault|failed|timeout|hang).*(?:KFD|GPUVM|GPU VM)', re.I)


def command(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    check(result.returncode == 0, f'command failed: {args[0]}: {result.stderr.strip()}')
    return result.stdout


def mem_available(text):
    for line in text.splitlines():
        if line.startswith('MemAvailable:'):
            value = int(line.split()[1])
            check(value >= MIN_MEM_KIB, f'MemAvailable below 8 GiB: {value} KiB')
            return value
    raise ValueError('MemAvailable unavailable')


def gpu_device():
    devices = [p for p in Path('/sys/class/drm').glob('card[0-9]*')
               if re.fullmatch(r'card\d+',p.name) and (p/'device/vendor').is_file()
               and (p/'device/vendor').read_text().strip() == '0x1002']
    check(len(devices) == 1, 'requires exactly one identified AMD GPU')
    return devices[0]/'device'


def resource_sample(device):
    return dict(time=datetime.now(timezone.utc).isoformat(),
                mem_available_kib=mem_available(Path('/proc/meminfo').read_text()),
                vram_used=int((device/'mem_info_vram_used').read_text()),
                gpu_busy_percent=int((device/'gpu_busy_percent').read_text()))


def gpu_clients():
    # Root is required so another user's GPU process cannot be silently hidden.
    devices = [Path('/dev/kfd'), *Path('/dev/dri').glob('renderD*'), *Path('/dev/dri').glob('card*')]
    check(all(p.exists() for p in devices) and len(devices) >= 3, 'GPU device nodes missing')
    numbers = {p.stat().st_rdev for p in devices}
    clients = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc/'fd').iterdir():
                try:
                    st = fd.stat()
                except FileNotFoundError:
                    continue
                # Only character devices; regular file st_rdev is usually zero.
                import stat
                if stat.S_ISCHR(st.st_mode) and st.st_rdev in numbers:
                    clients.append(int(proc.name))
                    break
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise ValueError('cannot audit GPU process ownership') from exc
    return sorted(clients)


def idle(device, baseline=None):
    sample = resource_sample(device)
    clients = gpu_clients()
    check(not clients, f'GPU occupied by processes: {clients}')
    check(sample['gpu_busy_percent'] == 0, 'GPU busy')
    limit = MAX_IDLE_VRAM if baseline is None else min(MAX_IDLE_VRAM, baseline + 64*1024*1024)
    check(0 <= sample['vram_used'] <= limit, 'GPU allocation not idle/released')
    return sample


class Journal:
    def __init__(self, output):
        self.output = output
        rows = self.read(['-n','1'])
        check(bool(rows) and '__CURSOR' in rows[-1], 'kernel journal cursor unavailable')
        self.cursor = rows[-1]['__CURSOR']
        (output/'kernel_baseline.json').write_bytes(encoded(rows[-1]))
        self.errors = []

    @staticmethod
    def read(extra):
        raw = command(['journalctl','--quiet','-k','-b','--no-pager','-o','json',*extra])
        return [json.loads(line) for line in raw.splitlines() if line.strip()]

    def poll(self):
        rows = self.read(['--after-cursor', self.cursor])
        with (self.output/'kernel_delta.jsonl').open('a') as log:
            for row in rows:
                check('__CURSOR' in row and isinstance(row.get('MESSAGE'), str), 'unreadable kernel entry')
                log.write(json.dumps(row, sort_keys=True)+'\n')
                self.cursor = row['__CURSOR']
                if ERROR.search(row['MESSAGE']):
                    self.errors.append(row)
        check(not self.errors, 'new AMDGPU/MES WAIT_REG_MEM/ring-full/reset/KFD/GPUVM error')


def mounted(path):
    return '/p5/' + str(path.relative_to(DATA))


def select_current(output, receipt):
    check(receipt.get('training_validated') is True and receipt.get('clean_gpu_delta') is True
          and receipt.get('clean_resource_release') is True, 'selection gates incomplete')
    check(output.parent == DEST and output.is_dir(), 'selection path')
    alias = DEST/'current'
    check(not alias.exists() or alias.is_symlink(), 'current is not a symlink')
    temporary = DEST/f'.current-{output.name}'
    temporary.symlink_to(output.name)
    os.replace(temporary, alias)


def run(run_id):
    check(os.geteuid() == 0, 'run launcher with sudo: complete GPU process/journal visibility requires root')
    check(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', run_id)) and run_id != 'current', 'unsafe run ID')
    validate_dataset()
    DATA.mkdir(parents=True, exist_ok=True)
    lock = (DATA/'.p511-training.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    DEST.mkdir(parents=True, exist_ok=True)
    output = DEST/run_id
    output.mkdir()  # Never overwrite or resume an old run's evidence.
    name = f'p511-{run_id}'
    created = False
    attached = None
    journal = None
    log = None
    uid, gid = int(os.environ.get('SUDO_UID',os.getuid())), int(os.environ.get('SUDO_GID',os.getgid()))
    os.chown(output,uid,gid)
    receipt = dict(stage='P5.11', run_id=run_id, status='FAILED',
                   training_validated=False, clean_gpu_delta=False, clean_resource_release=False,
                   quality_acceptance='pending_future_independent_evaluation', image=IMAGE,
                   parent_alias=str(PARENT), hsa_use_svm='0')
    (output/'runtime_manifest.json').write_bytes(encoded(receipt))
    try:
        device = gpu_device()
        journal = Journal(output)
        before = idle(device)
        receipt['resources_before'] = before
        parent = PARENT.resolve(strict=True)
        check(parent.is_relative_to(DATA/'adapters/electronics-foundation-v3') and parent.name != 'current', 'parent outside selected v3')
        parent_config = json.loads((parent/'adapter_config.json').read_text())
        check(parent_config.get('r') == 8 and parent_config.get('peft_type') == 'LORA', 'parent LoRA rank/type')
        check((MODEL/'model.safetensors.index.json').is_file(), 'local checkpoint missing')
        parent_hashes = {p.name:digest(p.read_bytes()) for p in [parent/'adapter_config.json',parent/'adapter_model.safetensors']}
        receipt.update(parent_resolved=str(parent), parent_hashes=parent_hashes,
                       dataset_sha256=digest((HERE/MIX_NAME).read_bytes()),
                       git_sha=command(['git','-c',f'safe.directory={ROOT}','-C',str(ROOT),'rev-parse','HEAD']).strip(),
                       image_id=command(['docker','image','inspect','--format','{{.Id}}',IMAGE]).strip())
        (output/'runtime_manifest.json').write_bytes(encoded(receipt))
        script = '/workspace/deploy/stage-p5/training/automotive_v1/train_automotive_specialization_v1.py'
        args = ['docker','create','--name',name,'--network=none','--memory=48g','--memory-swap=48g',
                '--user',f'{uid}:{gid}','--device=/dev/kfd','--device=/dev/dri','--ipc=private','--shm-size=8g',
                '--cap-drop=ALL','--security-opt=no-new-privileges',
                '-e','HSA_USE_SVM=0','-e','HF_HUB_OFFLINE=1','-e','TRANSFORMERS_OFFLINE=1',
                '-e','HOME=/tmp','-e','HF_HOME=/tmp/hf-cache','-e',f'P5_GIT_SHA={receipt["git_sha"]}',
                '-v',f'{ROOT}:/workspace:ro','-v',f'{MODEL}:{mounted(MODEL)}:ro',
                '-v',f'{parent}:{mounted(parent)}:ro','-v',f'{output}:{mounted(output)}:rw']
        for group in ('render','video'):
            import grp
            args += ['--group-add',str(grp.getgrnam(group).gr_gid)]
        args += [receipt['image_id'],'python3',script,'--model-dir',mounted(MODEL),
                 '--dataset',f'/workspace/deploy/stage-p5/training/automotive_v1/{MIX_NAME}',
                 '--output-dir',mounted(output),'--steps','64','--max-length','1024',
                 '--seed',str(SEED),'--lora-r','8','--lr','0.00002','--shuffle',
                 '--adapter-dir',mounted(parent),'--purpose','P5.11 training-only automotive specialization; quality acceptance pending future evaluation']
        (output/'container_command.json').write_bytes(encoded(args))
        command(args)
        created = True
        idle(device)  # Recheck after preparation, immediately before start.
        journal.poll()
        log = (output/'training.log').open('w')
        attached = subprocess.Popen(['docker','start','--attach',name],stdout=log,stderr=subprocess.STDOUT)
        while attached.poll() is None:
            journal.poll()
            sample = resource_sample(device)
            with (output/'resources.jsonl').open('a') as telemetry:
                telemetry.write(json.dumps(sample,sort_keys=True)+'\n')
            time.sleep(1)
        check(attached.returncode == 0, f'training process failed: {attached.returncode}')
        state = json.loads(command(['docker','inspect','--format','{{json .State}}',name]))
        (output/'container_state.json').write_bytes(encoded(state))
        check(state.get('Status') == 'exited' and state.get('ExitCode') == 0
              and not state.get('OOMKilled') and not state.get('Error'), 'container did not exit cleanly')
        journal.poll()
        manifest = validate_adapter(output)
        check(manifest['config']['adapter_dir'] == mounted(parent), 'trained parent mismatch')
        check(parent_hashes == {p.name:digest(p.read_bytes()) for p in [parent/'adapter_config.json',parent/'adapter_model.safetensors']}, 'parent changed during run')
        receipt['training_validated'] = True
        command(['docker','rm',name])
        created = False
        # Five consecutive clean samples after container exit/removal.
        for _ in range(5):
            time.sleep(1)
            journal.poll()
            receipt['resources_after'] = idle(device,before['vram_used'])
        receipt['clean_resource_release'] = True
        journal.poll()
        receipt['clean_gpu_delta'] = True
        receipt['status'] = 'PASS'
        (output/'runtime_manifest.json').write_bytes(encoded(receipt))
        select_current(output, receipt)
        print(f'P5_11_TRAINING=PASS adapter={output}; quality acceptance pending future evaluation')
    except BaseException as exc:
        receipt['status'] = 'FAILED'
        receipt['failure'] = str(exc)
        raise
    finally:
        if created:
            # Remove only this run's named container; preserve all bind-mounted evidence.
            try:
                state = command(['docker','inspect','--format','{{json .State}}',name])
                (output/'container_state_failure.json').write_text(state)
            except Exception as exc:
                receipt['state_capture_error'] = str(exc)
            try:
                command(['docker','rm','--force',name])
            except Exception as exc:
                receipt['cleanup_error'] = str(exc)
        if attached is not None and attached.poll() is None:
            try:
                attached.wait(timeout=30)
            except subprocess.TimeoutExpired:
                attached.terminate()
                receipt['attach_cleanup_error'] = 'docker attach did not exit after cleanup'
        if log is not None:
            log.close()
        if receipt['status'] != 'PASS':
            try:
                if journal is not None:
                    journal.poll()
            except Exception as exc:
                receipt['kernel_failure'] = str(exc)
            try:
                receipt['failure_release_sample'] = idle(gpu_device())
            except Exception as exc:
                receipt['release_error'] = str(exc)
        (output/'runtime_manifest.json').write_bytes(encoded(receipt))
        lock.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id',default='automotive-v1-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    args = ap.parse_args()
    def interrupted(signum, frame):
        raise RuntimeError(f'interrupted by signal {signum}')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    run(args.run_id)

if __name__ == '__main__':
    main()
