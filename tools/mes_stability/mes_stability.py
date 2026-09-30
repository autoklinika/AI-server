#!/usr/bin/env python3
"""Read-only audit and fail-closed, single-container ROCm diagnostic runner.

No driver/boot changes, training data, adapters, automatic recovery or promotion.
Standard library only on host; workload uses the existing pinned PyTorch image.
"""
import argparse
import collections
import fcntl
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
import uuid

GIB = 1024 ** 3
VARIANTS = {
    'A': {}, 'B': {'HSA_USE_SVM': '0'}, 'C': {'HSA_ENABLE_SDMA': '0'},
    'D': {'HSA_USE_SVM': '0', 'HSA_ENABLE_SDMA': '0'},
    'E': {'PYTORCH_ALLOC_CONF': 'backend:native,expandable_segments:True'},
}
PATTERNS = {
    'mes_wait': r'MES.*(?:failed|timeout).*WAIT_REG_MEM',
    'mes_full': r'MES ring buffer is full',
    'mes_other': r'MES.*(?:fail|timeout|unrecoverable|error)',
    'gpuvm': r'(?:page fault|GPUVM.*(?:fault|error)|protection_fault|VM_L2_PROTECTION)',
    'kfd': r'(?:kfd.*(?:error|fail|timeout)|failed to (?:evict|restore).*queue)',
    'svm_warning': r'(?:svm_range_\w+|amdgpu_amdkfd_restore_\w+).*hogged',
    'gpu_reset': r'GPU reset',
    'iommu_sva': r'(?:iommu.*(?:failed|\bfault\b|\berror\b)|\bSVA\b.*(?:failed|\bfault\b|\berror\b)|AMD-Vi.*(?:IO_PAGE_FAULT|INVALID))',
    'oom': r'(?:out of memory|oom-kill|killed process.*total-vm)',
    'watchdog': r'(?:watchdog.*(?:trigger|lockup)|soft lockup|hard lockup)',
}

def classify(message):
    hits = [k for k, p in PATTERNS.items() if re.search(p, message, re.I)]
    if 'mes_wait' in hits:
        hits.remove('mes_other')  # categories are disjoint within MES
    return hits

def command(argv, timeout=15, check=True):
    p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'{argv[0]} failed ({p.returncode}): {p.stderr[-500:]}')
    return p

def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    tmp.replace(path)

def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()

def gpu_path():
    matches = [p for p in Path('/sys/class/drm').glob('card[0-9]*/device')
               if re.fullmatch(r'card[0-9]+', p.parent.name) and (p / 'vendor').read_text().strip() == '0x1002']
    if len(matches) != 1:
        raise RuntimeError('exactly one AMD GPU required; explicit selection needed otherwise')
    return matches[0]

def telemetry(gpu):
    values = {}
    for name in ('mem_info_vram_used', 'mem_info_vram_total', 'mem_info_gtt_used', 'gpu_busy_percent'):
        values[name] = int((gpu / name).read_text())  # unavailable required sensor => stop
    values['mem_available_bytes'] = int(re.search(r'MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text())[1]) * 1024
    values['temperatures_c'] = {p.name + ':' + p.parent.name: int(p.read_text()) / 1000
                              for p in gpu.glob('hwmon/hwmon*/temp*_input')}
    values['loadavg'] = Path('/proc/loadavg').read_text().strip()
    values['memory_pressure'] = Path('/proc/pressure/memory').read_text().strip()
    return values

def wait_release(gpu, baseline_used, journal, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        sample = telemetry(gpu)
        if journal and journal.poll():
            return sample
        if sample['mem_info_vram_used'] <= baseline_used + GIB or time.monotonic() >= deadline:
            return sample
        time.sleep(0.2)

def preflight_reason(counts, sample, min_available=8*GIB):
    if any(counts.values()):
        return 'BOOT_TAINTED: previous fault/warning in this boot; no automatic recovery'
    if sample['mem_info_vram_used'] > 2*GIB or sample['gpu_busy_percent'] > 5:
        return 'GPU_OCCUPIED: isolate GPU through approved platform maintenance workflow'
    if sample['mem_available_bytes'] < min_available:
        return 'HOST_MEMORY_LOW'
    return None

def kernel_records(boot='0', cursor=None):
    argv = ['journalctl', '-k', '-b', str(boot), '--no-pager', '-o', 'json']
    if cursor:
        argv += ['--after-cursor', cursor]
    p = command(argv, timeout=30)
    rows = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    if not rows and not cursor:
        raise RuntimeError('kernel journal unavailable/empty; cannot protect workload')
    return rows

def count_records(rows):
    c = collections.Counter()
    for row in rows:
        c.update(classify(row.get('MESSAGE', '')))
    return dict(c)

def git_state(root):
    return {'sha': command(['git', '-C', str(root), 'rev-parse', 'HEAD']).stdout.strip(),
            'dirty': bool(command(['git', '-C', str(root), 'status', '--porcelain']).stdout)}

def audit(out, boots, image):
    out.mkdir(parents=True, exist_ok=False)
    summary = []
    for b in range(0, -boots, -1):
        try:
            rows = kernel_records(str(b))
            # Retain full kernel logs locally; never commit unrelated host/network logs.
            save(out / f'kernel-{b}.json', rows)
            hits = [r for r in rows if classify(r.get('MESSAGE', ''))]
            summary.append({'boot_offset': b, 'boot_id': rows[0].get('_BOOT_ID'),
                            'counts': count_records(rows), 'events': hits})
        except Exception as e:
            summary.append({'boot_offset': b, 'error': str(e)})
    save(out / 'history.json', summary)
    commands = {
        'uname': ['uname', '-a'], 'pci': ['lspci', '-nnk', '-d', '1002:'],
        'packages': ['dpkg-query', '-W', 'linux-firmware', 'linux-image-' + os.uname().release],
        'module': ['/usr/sbin/modinfo', 'amdgpu'],
        'docker_info': ['docker', 'info', '--format', '{{json .}}'],
        'image': ['docker', 'image', 'inspect', image],
        'services': ['systemctl', '--failed', '--no-pager'],
    }
    for name, argv in commands.items():
        try:
            p = command(argv, check=False)
            save(out / (name + '.json'), {'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        except Exception as e:
            save(out / (name + '.json'), {'error': str(e)})
    paths = ['/proc/cmdline', '/proc/meminfo', '/etc/os-release', '/boot/config-' + os.uname().release]
    for pattern in ['/sys/module/amdgpu/parameters/*', '/sys/module/ttm/parameters/*',
                    '/sys/class/kfd/kfd/topology/nodes/*/properties', '/sys/class/kfd/kfd/topology/nodes/*/name',
                    '/sys/class/drm/card*/device/firmware_version/*', '/sys/class/drm/card*/device/vbios*']:
        paths += glob.glob(pattern)
    data = {}
    for p in paths:
        try:
            data[p] = Path(p).read_text()
        except OSError as e:
            data[p] = {'unavailable': str(e)}
    data['gpu'] = telemetry(gpu_path())
    save(out / 'sysfs.json', data)
    print(json.dumps({'audit': str(out), 'boots': [{k:v for k,v in r.items() if k != 'events'} for r in summary]}))

class Journal:
    """Cursor-bound follower. Death, malformed JSON or missing cursor fails closed."""
    def __init__(self, cursor, output):
        self.proc = subprocess.Popen(['journalctl', '-k', '-b', '0', '--after-cursor', cursor,
                                      '-f', '--no-pager', '-o', 'json'], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.buffer = b''
        self.output = output.open('a')
        self.counts = collections.Counter()
        self.first_error = None
    def poll(self):
        if self.proc.poll() is not None:
            raise RuntimeError('journal follower exited; monitoring lost')
        while select.select([self.proc.stdout], [], [], 0)[0]:
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('journal follower EOF')
            self.buffer += chunk
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                if not line.strip():
                    continue
                row = json.loads(line)
                if '__CURSOR' not in row:
                    raise RuntimeError('journal cursor missing')
                self.output.write(json.dumps(row) + '\n'); self.output.flush()
                hits = classify(row.get('MESSAGE', ''))
                self.counts.update(hits)
                if hits and self.first_error is None:
                    self.first_error = row
        return self.first_error
    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill(); self.proc.wait(timeout=3)
        self.output.close()

def docker_args(args, root, name, image_id):
    argv = ['docker', 'create', '--name', name, '--label', 'ai-platform.p5-mes-diagnostic=true',
            '--network', 'none', '--memory', '48g', '--memory-swap', '48g',
            '--pids-limit', '512', '--user', f'{os.getuid()}:{os.getgid()}',
            '--group-add', str(Path('/dev/kfd').stat().st_gid),
            '--group-add', str(Path('/dev/dri/renderD128').stat().st_gid),
            '--device', '/dev/kfd', '--device', '/dev/dri', '--ipc', 'host',
            '-v', f'{root}:/workspace:ro', '-e', 'HOME=/tmp', '-e', 'PYTHONUNBUFFERED=1']
    for k, v in VARIANTS[args.variant].items():
        argv += ['-e', f'{k}={v}']
    if args.profile == 'qwen':
        model = Path(args.model_dir).resolve(strict=True)
        if not (model / 'model.safetensors.index.json').is_file():
            raise RuntimeError('buffered base model index missing')
        argv += ['-v', f'{model}:/model:ro']
    argv += [image_id, 'python3', '/workspace/tools/mes_stability/workload.py',
             '--seconds', str(args.seconds), '--resident-gib', str(args.resident_gib),
             '--seed', str(args.seed), '--profile', args.profile]
    return argv

def run(args):
    root = Path(__file__).resolve().parents[2]
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    result = {'status': 'BLOCKED', 'variant': args.variant, 'environment_overrides': VARIANTS[args.variant],
              'boot_id': boot_id(), 'kernel': os.uname().release, 'started_at_unix': time.time(), 'git': git_state(root), 'duration_requested_s': args.seconds,
              'resident_gib': args.resident_gib, 'seed': args.seed, 'profile': args.profile,
              'peak_vram_bytes': None, 'min_mem_available_bytes': None, 'error_counts': {},
              'workload_exit_code': None, 'gate': 'NOT_PASSED'}
    name = 'p5-mes-' + uuid.uuid4().hex[:12]
    journal = None
    created = False
    started = False
    logs = None
    lock = None
    before = None
    last_cursor = None
    def interrupted(signum, frame):
        raise RuntimeError(f'interrupted by signal {signum}')
    old_handlers = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        if args.seconds <= 0 or args.resident_gib < 0 or args.resident_gib > 64:
            raise ValueError('seconds must be positive; resident GiB must be 0..64')
        lock = open('/tmp/ai-platform-p5-mes.lock', 'a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows = kernel_records()
        last_cursor = rows[-1]['__CURSOR']
        result['baseline_cursor'] = last_cursor
        result['baseline_counts'] = count_records(rows)
        gpu = gpu_path()
        before = telemetry(gpu)
        before['failed_services'] = command(['systemctl', '--failed', '--no-legend', '--plain', '--no-pager']).stdout
        save(out / 'preflight.json', before)
        reason = preflight_reason(result['baseline_counts'], before)
        if reason:
            raise RuntimeError(reason)
        image = json.loads(command(['docker', 'image', 'inspect', args.image]).stdout)[0]
        result['image_id'] = image['Id']
        result['image_environment'] = image['Config'].get('Env', [])
        save(out / 'image.json', {'Id': image['Id'], 'RepoDigests': image.get('RepoDigests'), 'Config': image['Config']})
        journal = Journal(last_cursor, out / 'kernel-new.jsonl')
        if journal.poll():
            raise RuntimeError('new kernel fault before launch')
        argv = docker_args(args, root, name, image['Id'])
        save(out / 'launch.json', argv)
        result['container_name'] = name
        command(argv); created = True
        if journal.poll():
            raise RuntimeError('new kernel fault before docker start')
        command(['docker', 'start', name]); started = True
        result['status'] = 'RUNNING'
        save(out / 'result.json', result)
        log_file = (out / 'workload.log').open('w')
        logs = subprocess.Popen(['docker', 'logs', '-f', name], stdout=log_file, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + args.seconds + 300
        next_sample = 0
        with (out / 'telemetry.jsonl').open('w') as f:
            while True:
                if journal.poll():
                    raise RuntimeError('NEW_KERNEL_ERROR')
                if boot_id() != result['boot_id']:
                    raise RuntimeError('boot changed')
                now = time.monotonic()
                if now >= deadline:
                    raise RuntimeError('workload deadline exceeded')
                if now >= next_sample:
                    sample = telemetry(gpu)
                    sample.update(elapsed_s=now-start, timestamp=time.time(), error_counts=dict(journal.counts))
                    f.write(json.dumps(sample) + '\n'); f.flush()
                    result['peak_vram_bytes'] = max(result['peak_vram_bytes'] or 0, sample['mem_info_vram_used'])
                    result['min_mem_available_bytes'] = min(result['min_mem_available_bytes'] or sample['mem_available_bytes'], sample['mem_available_bytes'])
                    if sample['mem_available_bytes'] < 8*GIB:
                        raise RuntimeError('host MemAvailable below 8 GiB')
                    if max(sample['temperatures_c'].values(), default=0) >= 90:
                        raise RuntimeError('GPU temperature reached diagnostic 90 C stop threshold')
                    state = json.loads(command(['docker', 'inspect', '--format', '{{json .State}}', name], timeout=3).stdout)
                    save(out / 'container-state.json', state)
                    if not state['Running']:
                        result['workload_exit_code'] = state['ExitCode']
                        if state['ExitCode'] != 0 or state['OOMKilled']:
                            raise RuntimeError('workload failed or cgroup OOM')
                        result['status'] = 'PASS_RUN_ONLY'
                        break
                    next_sample = now + 1
                time.sleep(0.1)
    except Exception as e:
        result['reason'] = str(e)
        result['status'] = 'FAIL' if started else 'BLOCKED'
    finally:
        # Stop only the container created by this run. Never reset/unbind GPU.
        if created:
            try:
                st = json.loads(command(['docker', 'inspect', '--format', '{{json .State}}', name], timeout=3).stdout)
                if st['Running']:
                    kill_time = time.monotonic()
                    command(['docker', 'kill', name], timeout=5)
                    result['kill_request_s'] = time.monotonic() - kill_time
                st = json.loads(command(['docker', 'inspect', '--format', '{{json .State}}', name], timeout=3).stdout)
                result['workload_exit_code'] = st['ExitCode']
                save(out / 'container-final-state.json', st)
                if st['Running']:
                    raise RuntimeError('container remains running; do not run next variant')
                result['container_stopped'] = True
            except Exception as e:
                result['cleanup_error'] = str(e)
                result['status'] = 'FAIL_CONTAINMENT'
        if logs:
            try:
                logs.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logs.terminate()
            log_file.close()
            if result['status'] == 'PASS_RUN_ONLY':
                try:
                    lines = (out / 'workload.log').read_text().splitlines()
                    completed = [json.loads(l) for l in lines if l.startswith('{') and json.loads(l).get('phase') == 'completed']
                    if len(completed) != 1 or completed[0]['measured_s'] < args.seconds or completed[0]['profile'] != args.profile:
                        raise RuntimeError('missing/short workload completion evidence')
                    result['measured_workload_s'] = completed[0]['measured_s']
                    result['torch_peak_allocated'] = completed[0]['peak_allocated']
                    result['torch_peak_reserved'] = completed[0]['peak_reserved']
                except Exception as e:
                    result['status'] = 'FAIL_EVIDENCE'
                    result['completion_error'] = str(e)
        if before:
            try:
                after = wait_release(gpu, before['mem_info_vram_used'], journal)
                after['failed_services'] = command(['systemctl', '--failed', '--no-legend', '--plain', '--no-pager']).stdout
                result['host_regression_free'] = (after['failed_services'] == before['failed_services'] and after['mem_available_bytes'] >= 8*GIB and after['mem_info_vram_used'] <= before['mem_info_vram_used'] + GIB)
                save(out / 'postflight.json', after)
                if result['status'] == 'PASS_RUN_ONLY' and after['mem_info_vram_used'] > before['mem_info_vram_used'] + GIB:
                    result['status'] = 'FAIL_CLEANUP'
                result['postflight_mem_available_bytes'] = after['mem_available_bytes']
            except Exception as e:
                result['postflight_error'] = str(e)
                result['status'] = 'FAIL_MONITOR'
        if last_cursor:
            try:
                final_rows = kernel_records(cursor=last_cursor)
                save(out / 'kernel-final.json', final_rows)
                result['error_counts'] = count_records(final_rows)
                if journal:
                    for key, value in journal.counts.items():
                        result['error_counts'][key] = max(value, result['error_counts'].get(key, 0))
                if any(result['error_counts'].values()):
                    result['status'] = 'FAIL' if started else 'BLOCKED'
                    result.setdefault('reason', 'new kernel error during teardown')
            except Exception as e:
                result['journal_final_error'] = str(e)
                result['status'] = 'FAIL_MONITOR'
        if journal:
            if journal.first_error:
                save(out / 'first-error.json', journal.first_error)
            journal.close()
        result['elapsed_s'] = time.monotonic() - start
        result['ended_at_unix'] = time.time()
        save(out / 'result.json', result)
        if lock:
            lock.close()
        for s, h in old_handlers.items():
            signal.signal(s, h)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS_RUN_ONLY' else 1

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('audit'); a.add_argument('--output', required=True); a.add_argument('--boots', type=int, default=6)
    a.add_argument('--image', default='ai-platform-p5-train:rocm7.2.1-v1')
    r = sub.add_parser('run'); r.add_argument('--output', required=True)
    r.add_argument('--image', default='ai-platform-p5-train:rocm7.2.1-v1')
    r.add_argument('--variant', choices=VARIANTS, required=True)
    r.add_argument('--seconds', type=int, default=60)
    r.add_argument('--resident-gib', type=float, default=2)
    r.add_argument('--seed', type=int, default=20260930)
    r.add_argument('--profile', choices=['synthetic', 'qwen'], default='synthetic')
    r.add_argument('--model-dir', default='/srv/ai-data/training/p5/models/Qwen3.8-27B-buffered-512m')
    args = p.parse_args()
    if args.cmd == 'audit':
        audit(Path(args.output), args.boots, args.image); return 0
    return run(args)

if __name__ == '__main__':
    sys.exit(main())
