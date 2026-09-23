#!/usr/bin/env python3
"""Stage F supervisor gate. Private recovery material never leaves local storage."""
from contextlib import closing
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('stage_e_primitives', ROOT / 'deploy/stage-e/autopilot/gate.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
BASE = Path('/opt/ai-platform/releases/stage-e-38fff86f7704')
BASE_SHA = '38fff86f7704fcee92d66a750c033a9ec69ff084'
STATE = Path('/var/lib/ai-platform/stage-f')
HERMES = Path('/srv/ai-data/hermes')
SOURCE = HERMES / 'hermes-agent'
PIN = '79445a496c86a19332ad786494b8384d2167e2d0'
PATCHED = ('agent/turn_api_request.py', 'gateway/run_inbound.py', 'gateway/run_turn_runner.py')
ORIGINAL_PATCH_HASHES = {'agent/turn_api_request.py': 'a81c83b14d93f801a7082b0900111aa7345f0b3f42b2f50dba1f3d93a63f7405', 'gateway/run_inbound.py': '3d6ff79be1ae9f8ebcffb409260992ccff7e9673ed7a48c281f088cda7f9de8c', 'gateway/run_turn_runner.py': '7d59a9585e359f5ad3cc16bbd3b48e2cf30663fddec89a3422934644ccdbd476'}
PLUGIN = HERMES / 'plugins/ai-platform-messaging'
RESOURCE_CLIENT = Path('/usr/local/libexec/ai-server/hermes_resource_queue.py')
GPU_UNIT = Path('/etc/systemd/system/ai-gateway.service.d/96-gpu-residency.conf')
IMAGE_BINARIES = ('generate-image', 'generate-image-edit')
MANAGED_FILES = {
    **{Path('/usr/local/bin') / name: 'deploy/stage-f/bin/' + name for name in IMAGE_BINARIES},
    Path('/usr/local/libexec/ai-server/qwen_prompt_compiler.py'): 'tools/local_video/qwen_prompt_compiler.py',
    Path('/usr/local/libexec/ai-server/qwen_prompt_compiler_stage30.py'): 'tools/local_video/qwen_prompt_compiler_stage30.py',
    Path('/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py'): 'tools/local_image/hermes_foto_prompt_compiler.py',
}
CONFIG = HERMES / 'config.yaml'
e.D6 = BASE  # Existing client fingerprints are identical in the E baseline.
require, run = e.require, e.run

# Stage F updates the supported RM client's transition timeout and fail-closed
# cleanup. Validate installed bytes against the active immutable release.
_original_clients, _original_runtime = e.clients, e.runtime

def clients():
    previous = e.D6
    try:
        current = e.CURRENT.resolve()
        e.D6 = current if current.name.startswith('stage-f-') else BASE
        result = _original_clients()
        for actual, relative in MANAGED_FILES.items():
            expected = current / 'services/ai-bridge' / relative
            if expected.exists():
                require(actual.read_bytes() == expected.read_bytes())
        return result
    finally:
        e.D6 = previous

def runtime(release, cfg, baseline=None, require_idle=True):
    expected = {**baseline, 'clients': clients()} if baseline else None
    return _original_runtime(release, cfg, expected, require_idle)

e.clients, e.runtime = clients, runtime


def hermes_git(args):
    name, uid, home = e.hermes_account()
    return run(['runuser', '-u', name, '--', 'git', '-C', SOURCE, *args])


def verify_release(path):
    stage = dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())['stage'].lower()
    require(stage in ('e', 'f'))
    return e.verify_release(path, stage)


def preflight():
    marker = STATE / 'gpu-blocked.json'
    if marker.exists():
        require(e.read(marker)['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    require(e.CURRENT.resolve() == BASE)
    require(verify_release(BASE)['source_git_sha'] == BASE_SHA)
    e.runtime(BASE, e.config())
    e.hermes_state()
    require(hermes_git(['rev-parse', 'HEAD']) == PIN)
    require(set(hermes_git(['diff', '--name-only']).splitlines()) == set(PATCHED))
    require(not hermes_git(['diff', '--cached', '--name-only']))
    require(not hermes_git(['ls-files', '--others', '--exclude-standard']))
    require(not PLUGIN.exists())
    e.media_preflight()


def backup_database(path, target):
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as dest:
        source.backup(dest)
        require(dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok')


def snapshot(state):
    recovery = state / 'hermes-recovery'
    recovery.mkdir(mode=0o700)
    manifest = {'pin': PIN, 'files': {}, 'databases': {}}
    # An exact upstream archive + dirty patch and original touched bytes allow
    # reconstruction even if the live checkout is later lost.
    name, uid, home = e.hermes_account()
    with (recovery / 'upstream.tar').open('xb') as stream:
        subprocess.run(['runuser', '-u', name, '--', 'git', '-C', SOURCE, 'archive', PIN], stdout=stream, check=True)
    (recovery / 'dirty.patch').write_text(hermes_git(['diff', '--binary']) + '\n')
    paths = [CONFIG, RESOURCE_CLIENT, *[SOURCE / p for p in PATCHED],
             *MANAGED_FILES]
    manifest['gpu_unit_existed'] = GPU_UNIT.exists()
    if GPU_UNIT.exists():
        paths.append(GPU_UNIT)
    for index, path in enumerate(paths):
        target = recovery / f'file-{index}'
        shutil.copy2(path, target)
        info = path.stat()
        manifest['files'][str(path)] = {'copy': target.name, 'sha256': e.digest(target),
            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
    # Online SQLite backup gives consistent DB pages without copying active WALs.
    dbs = list(HERMES.glob('*.db'))
    for index, path in enumerate(dbs):
        target = recovery / f'state-{index}.sqlite'
        manifest['databases'][str(path)] = target.name
        backup_database(path, target)
    with tarfile.open(recovery / 'config-state-integration.tar', 'x') as archive:
        for path in HERMES.iterdir():
            if path.is_file() and not path.name.endswith(('.db', '.db-wal', '.db-shm', '.lock')):
                archive.add(path, arcname='hermes/' + path.name, recursive=False)
        for directory in ('sessions', 'state', 'skills', 'hooks', 'cron', 'runtime', 'bin', 'plugins', 'platforms', 'pairing'):
            path = HERMES / directory
            if path.exists():
                archive.add(path, arcname='hermes/' + directory)
        archive.add('/usr/local/libexec/ai-server', arcname='integration/libexec')
        for binary in ('hermes-foto-dispatch', 'hermes-video-dispatch', 'generate-video-ltx23', 'generate-image', 'generate-image-edit'):
            path = Path('/usr/local/bin') / binary
            if path.exists():
                archive.add(path, arcname='integration/bin/' + binary)
    # Restore tests compare hashes/ownership for source/config. Stateful data is
    # recovery-only: never overwrite newer conversations during planned rollback.
    manifest['archives'] = {p.name: e.digest(p) for p in recovery.iterdir() if p.is_file()}
    e.write_once(recovery / 'manifest.json', manifest)
    for path in recovery.iterdir():
        path.chmod(0o400)
    recovery.chmod(0o500)
    return e.digest(recovery / 'manifest.json')


def verify_snapshot(state, baseline):
    recovery = state / 'hermes-recovery'
    require(e.digest(recovery / 'manifest.json') == baseline['hermes_snapshot'])
    manifest = e.read(recovery / 'manifest.json')
    require(manifest['pin'] == PIN)
    for filename, expected in manifest['archives'].items():
        require(e.digest(recovery / filename) == expected)
    return recovery, manifest


def atomic_restore(path, content, mode, uid, gid):
    temporary = path.with_name('.' + path.name + '.stage-f-' + uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, gid)
        temporary.chmod(mode)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def configure(candidate, state, baseline, rollback=False):
    import yaml
    recovery, manifest = verify_snapshot(state, baseline)
    require(hermes_git(['rev-parse', 'HEAD']) == PIN)
    require(not hermes_git(['diff', '--cached', '--name-only']))
    # Refuse unknown edits rather than overwriting them on either transition.
    require(set(hermes_git(['diff', '--name-only']).splitlines()).issubset(set(PATCHED)))
    for relative in PATCHED:
        path = SOURCE / relative
        saved = manifest['files'][str(path)]
        upstream = subprocess.check_output(['git', '-c', f'safe.directory={SOURCE}', '-C', str(SOURCE), 'show', f'{PIN}:{relative}'])
        if not rollback:
            require(path.read_bytes() in (upstream, (recovery / saved['copy']).read_bytes()))
    original = (recovery / manifest['files'][str(CONFIG)]['copy']).read_bytes()
    expected = yaml.safe_load(original)
    for command in ('foto', 'wideo'):
        expected['quick_commands'].pop(command)
    enabled = expected.setdefault('plugins', {}).setdefault('enabled', [])
    if 'ai-platform-messaging' not in enabled:
        enabled.append('ai-platform-messaging')
    disabled = expected['plugins'].get('disabled', [])
    require('ai-platform-messaging' not in disabled)
    candidate_config = yaml.safe_dump(expected, allow_unicode=True, sort_keys=False).encode()
    if not rollback:
        require(CONFIG.read_bytes() in (original, candidate_config))
    plugin_source = candidate / 'services/ai-bridge/integrations/hermes/ai-platform-messaging'
    if PLUGIN.exists() and not rollback:
        for filename in ('__init__.py', 'plugin.yaml'):
            expected_hash = e.read(state / 'installed.json')['plugin_hashes'][filename]
            require(e.digest(PLUGIN / filename) == expected_hash)
    if rollback:
        if not manifest['gpu_unit_existed']:
            GPU_UNIT.unlink(missing_ok=True)
        for path_string, info in manifest['files'].items():
            path = Path(path_string)
            atomic_restore(path, (recovery / info['copy']).read_bytes(), info['mode'], info['uid'], info['gid'])
            require(e.digest(path) == info['sha256'])
        if PLUGIN.exists():
            # Preserve a partial or externally modified plugin for diagnosis.
            quarantine = state / ('plugin-rollback-quarantine-' + uuid4().hex)
            shutil.copytree(PLUGIN, quarantine)
            shutil.rmtree(PLUGIN)
    else:
        for binary, relative in MANAGED_FILES.items():
            info = manifest['files'][str(binary)]
            atomic_restore(binary, (candidate / 'services/ai-bridge' / relative).read_bytes(),
                           info['mode'], info['uid'], info['gid'])
        GPU_UNIT.parent.mkdir(parents=True, exist_ok=True)
        atomic_restore(GPU_UNIT, (candidate / 'services/ai-bridge/deploy/systemd/stage-f/ai-gateway.service.d/96-gpu-residency.conf').read_bytes(),
                       0o644, 0, 0)
        info = manifest['files'][str(RESOURCE_CLIENT)]
        atomic_restore(RESOURCE_CLIENT, (candidate / 'services/ai-bridge/tools/hermes_resource_queue.py').read_bytes(),
                       info['mode'], info['uid'], info['gid'])
        for relative in PATCHED:
            path = SOURCE / relative
            info = manifest['files'][str(path)]
            content = subprocess.check_output(['git', '-c', f'safe.directory={SOURCE}', '-C', str(SOURCE), 'show', f'{PIN}:{relative}'])
            atomic_restore(path, content, info['mode'], info['uid'], info['gid'])
        info = manifest['files'][str(CONFIG)]
        atomic_restore(CONFIG, candidate_config, info['mode'], info['uid'], info['gid'])
        if not PLUGIN.exists():
            PLUGIN.parent.mkdir(exist_ok=True)
            staging = PLUGIN.with_name('.ai-platform-messaging-' + uuid4().hex)
            shutil.copytree(plugin_source, staging, ignore=shutil.ignore_patterns('__pycache__'))
            owner = HERMES.stat()
            for path in (staging, *staging.rglob('*')):
                os.chown(path, owner.st_uid, owner.st_gid)
            os.replace(staging, PLUGIN)
        require(not hermes_git(['status', '--porcelain']))


def require_no_media_workers():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        if any(b'--child-worker' == arg or b'--worker' == arg for arg in argv):
            require(not any(b'hermes_foto' in arg or b'hermes_video' in arg or b'internal_e2e.py' in arg for arg in argv))


def require_kernel_clear():
    spec = importlib.util.spec_from_file_location('stage_f_gpu_check', ROOT / 'deploy/stage-f/gpu_watch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kernel = run(['journalctl', '-k', '-b', '--no-pager', '-o', 'cat'])
    require(not module.GPU_ERROR.search(kernel))


def recover_gpu_quiesced(state):
    # Known-good E Python plus reviewed controller source; never execute a
    # failed candidate. Both ingress and Gateway are stopped, workers reaped.
    marker = Path('/var/lib/ai-platform-gpu/residency.blocked')
    temporary_marker = state / ('quiesced-gpu-' + uuid4().hex)
    script = """
import asyncio, sys
from pathlib import Path
import httpx
from ai_bridge.gateway.residency import GPUResidency
async def recover():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:11434', timeout=90, trust_env=False) as ollama, httpx.AsyncClient(base_url='http://127.0.0.1:8188', timeout=10, trust_env=False) as comfy:
        gpu = GPUResidency(ollama, comfy, Path(sys.argv[1]), idle_reserve_bytes=33554432)
        await gpu.enter_media()
        await gpu.leave_media()
asyncio.run(recover())
"""
    run([BASE / 'services/ai-bridge/.venv/bin/python', '-c', script, temporary_marker],
        timeout=200, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')})
    require_kernel_clear()
    if marker.exists():
        shutil.copy2(marker, state / ('recovered-marker-' + uuid4().hex))
        marker.unlink()


def messaging_boundary_smoke(model):
    ids = []
    for source in ('telegram-synthetic-a', 'telegram-synthetic-b', 'discord-synthetic'):
        result, headers = e.fetch(e.GATEWAY + '/clients/hermes/v1/chat/completions',
            {'model': model, 'messages': [{'role': 'user', 'content': 'Return OK.'}],
             'stream': False, 'max_tokens': 32, 'reasoning_effort': 'none'}, with_headers=True)
        require(bool(result['choices'][0]['message']['content'].strip()))
        ids.append(headers['X-AI-Job-Id'])
    require(len(set(ids)) == 3)
    name, uid, home = e.hermes_account()
    for platform in ('telegram', e.discord_smoke_target()):
        delivery = json.loads(run(['runuser', '-u', name, '--', 'env', f'HOME={home}',
            'HERMES_HOME=/srv/ai-data/hermes', f'XDG_RUNTIME_DIR=/run/user/{uid}',
            Path(home) / '.local/bin/hermes', 'send', '--to', platform, '--quiet', '--json',
            '[AI Platform Stage F] automated outbound compatibility probe ' + uuid4().hex[:8]], timeout=60))
        require(delivery.get('success') is True and not delivery.get('skipped') and not delivery.get('error'))


def switch(target, candidate, state, baseline):
    rollback = target == BASE
    require(e.CURRENT.resolve() in (BASE, candidate, Path(baseline.get('previous_candidate', str(BASE)))))
    verify_release(target)
    if not rollback:
        e.clients()  # Rollback validates the snapshot, never the failed candidate.
    recovering = bool(baseline.get('previous_candidate'))
    e.quiesce(baseline, allow_gateway_unavailable=rollback or recovering)
    e.require_hermes_stopped()
    e.comfy_idle()
    require_no_media_workers()
    # No ingress resume until both platform and matching Hermes configuration
    # validate. On any partial failure supervisor must invoke planned recovery.
    configure(candidate, state, baseline, rollback)
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge.service'])
    recover_gpu_quiesced(state)
    temporary = e.CURRENT.with_name('.stage-f-' + uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, e.CURRENT)
    run(['systemctl', 'start', 'ai-gateway.service', 'ai-bridge.service'])
    for attempt in range(40):
        try:
            e.runtime(target, e.config(), baseline)
            break
        except Exception:
            if attempt == 39:
                raise
            time.sleep(1)
    if not rollback:
        e.resume_ingress(baseline)


def rollback_hermes_probe():
    # Validate restored Hermes through its real CLI while external ingress stays
    # paused: Stage E does not contain the repaired residency boundary.
    name, uid, home = e.hermes_account()
    output = run(['runuser', '-u', name, '--', 'env', f'HOME={home}',
        'HERMES_HOME=/srv/ai-data/hermes', f'XDG_RUNTIME_DIR=/run/user/{uid}',
        Path(home) / '.local/bin/hermes', '-z', 'Return the word OK.'], timeout=180)
    require(bool(output.strip()))
    e.require_hermes_stopped()


def _smoke(phase, target, candidate, state, baseline):
    e.runtime(target, e.config(), baseline)
    before = [e.identity(u) for u in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')]
    evidence_dir = state / (phase + '-' + uuid4().hex)
    evidence_dir.mkdir(mode=0o700)
    from importlib.util import spec_from_file_location, module_from_spec
    harness_spec = spec_from_file_location('stage_f_probe', ROOT / 'deploy/stage-f/internal_e2e.py')
    harness = module_from_spec(harness_spec)
    harness_spec.loader.exec_module(harness)
    result = e.fetch(e.GATEWAY + '/api/chat', {'model': harness.configured_hermes_model(CONFIG),
        'messages': [{'role': 'user', 'content': 'Return OK.'}], 'stream': False,
        'think': False, 'options': {'num_predict': 16}})
    require(result.get('done') is True and result.get('eval_count', 0) > 0)
    e.api_smoke(e.config())
    e.wvc_smoke()
    if target == candidate:
        e.hermes_oneshot_smoke()
    else:
        rollback_hermes_probe()
    messaging_boundary_smoke(harness.configured_hermes_model(CONFIG))
    if target == candidate:
        require(not hermes_git(['status', '--porcelain']))
        e.quiesce(baseline)
        e.require_hermes_stopped()
        try:
            # Real local components; delivery sink is internal, not Telegram/Discord.
            name, uid, home = e.hermes_account()
            os.chown(evidence_dir, uid, HERMES.stat().st_gid)
            # Root-only evidence parent is intentionally not exposed to Hermes.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='stage-f-e2e-output-') as temporary:
                os.chown(temporary, uid, HERMES.stat().st_gid)
                output = Path(temporary) / 'internal.json'
                command = ['runuser', '-u', name, '--', 'env', f'HOME={home}',
                     f'PYTHONPATH={SOURCE}',
                     SOURCE / 'venv/bin/python',
                     candidate / 'services/ai-bridge/deploy/stage-f/internal_e2e.py',
                     '--media', '--output', output]
                with (evidence_dir / 'harness.log').open('x') as log:
                    completed = subprocess.run([str(a) for a in command], stdout=log, stderr=subprocess.STDOUT, timeout=10800)
                require(completed.returncode == 0)
                evidence = e.read(output)
                require(evidence['status'] == 'PASS' and len(evidence['media']) == 4)
                require(evidence['external_transport'] == 'DEFERRED/NOT TESTED')
                e.write_once(evidence_dir / 'internal.json', evidence)
        finally:
            # A harness assertion alone is not a reason to roll back a healthy
            # candidate. Restore ingress only when admission and services are safe.
            e.runtime(target, e.config(), baseline)
            e.resume_ingress(baseline)
    else:
        # Stage E lacks residency isolation. Do not run heavy legacy media here.
        e.comfy_idle()
        recovery, manifest = verify_snapshot(state, baseline)
        for path, info in manifest['files'].items():
            require(e.digest(path) == info['sha256'])
        require(not PLUGIN.exists())
    # Media cleanup must allow the same Ollama service to load/infer again.
    e.wvc_smoke()
    e.runtime(target, e.config(), baseline)
    if target == candidate:
        e.hermes_state()
    else:
        e.require_hermes_stopped()
    require(before == [e.identity(u) for u in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')])
    e.write_once(evidence_dir / 'provisional.json', {'release': target.name, 'time': time.time(), 'phase': phase,
        'compatibility': 'PASS', 'internal_e2e': 'PASS' if target == candidate else 'NOT APPLICABLE: E rollback',
        'external_transport': 'DEFERRED/NOT TESTED',
        'external_ingress': 'connected' if target == candidate else 'paused during legacy rollback'})
    return {'evidence': str(evidence_dir), 'release': target.name}


def smoke(phase, target, candidate, state, baseline):
    spec = importlib.util.spec_from_file_location('stage_f_gpu_watch', ROOT / 'deploy/stage-f/gpu_watch.py')
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    def contain():
        record = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'status': 'BLOCKED_GPU', 'release': str(e.CURRENT.resolve()), 'time': time.time()}
        temporary = STATE / ('gpu-blocked-' + uuid4().hex)
        temporary.write_text(json.dumps(record))
        os.replace(temporary, STATE / 'gpu-blocked.json')
        # Stop admission first. Preserve release bytes, journals and worker state.
        run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge-analysis.timer'], timeout=180)
        e.user_systemctl(['stop', 'hermes-gateway.service'])
    original_resume = e.resume_ingress
    with watch.KernelGuard(run, contain, state / (phase + '-kernel.log')) as guard:
        def safe_resume(baseline):
            guard.check()
            original_resume(baseline)
        e.resume_ingress = safe_resume
        try:
            result = _smoke(phase, target, candidate, state, baseline)
        finally:
            e.resume_ingress = original_resume
    evidence_dir = Path(result['evidence'])
    e.write_once(evidence_dir / 'pass.json', e.read(evidence_dir / 'provisional.json'))
    e.write_once(state / (phase + '.json'), result)


def recover_unmodified_baseline(sha):
    """Emergency runtime recovery before F cutover; never installs the candidate.

    Only available with the verified E release and original three dirty files.
    This repairs a stalled local model probe while retaining every source/config
    byte. It is not the mandatory Stage F rollback acceptance test.
    """
    require(e.CURRENT.resolve() == BASE)
    require(verify_release(BASE)['source_git_sha'] == BASE_SHA)
    require(hermes_git(['rev-parse', 'HEAD']) == PIN)
    require(set(hermes_git(['diff', '--name-only']).splitlines()) == set(PATCHED))
    require(not PLUGIN.exists())
    require(not any(STATE.glob('*/installed.json')))
    for relative, expected in ORIGINAL_PATCH_HASHES.items():
        require(e.digest(SOURCE / relative) == expected)
    e.comfy_idle()
    recovered_before = any(STATE.glob('baseline-recovery-*/runtime-restored.json'))
    kernel = run(['journalctl', '-k', '--since', '-5 minutes', '--no-pager', '-o', 'cat'])
    gpu_stalled = recovered_before and 'MES ring buffer is full.' in kernel
    if gpu_stalled:
        require(e.fetch('http://127.0.0.1:11434/api/ps').get('models') == [])
    directory = STATE / ('baseline-recovery-' + uuid4().hex)
    directory.mkdir(mode=0o700)
    snapshot_hash = snapshot(directory)
    baseline = {'clients': e.clients(), 'comfy': e.identity('comfyui.service'),
                'hermes_active': 'active', 'analysis_timer_active': run([
                    'systemctl', 'show', 'ai-bridge-analysis.timer', '-p', 'ActiveState', '--value'])}
    e.quiesce(baseline, allow_gateway_unavailable=True)
    e.require_hermes_stopped()
    # Admission jobs have no external media owner (Comfy queue was proven empty).
    # Stop Gateway before its backend, then start the same verified E processes.
    run(['systemctl', 'stop', 'ai-gateway.service'], timeout=180)
    if gpu_stalled:
        record = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'release': BASE.name, 'snapshot': snapshot_hash, 'source_sha': sha,
                  'status': 'BLOCKED_GPU', 'gateway': 'stopped', 'hermes': 'stopped',
                  'analysis_timer': 'paused', 'bridge': 'preserved', 'comfy': 'preserved_idle',
                  'reason': 'persistent AMD MES ring full after model service restart; no models loaded'}
        e.write_once(directory / 'gpu-blocked.json', record)
        if not (STATE / 'gpu-blocked.json').exists():
            e.write_once(STATE / 'gpu-blocked.json', record)
        print('BASELINE_RUNTIME=BLOCKED_GPU_INGRESS_PAUSED', flush=True)
        raise RuntimeError('host GPU recovery required')
    run(['systemctl', 'restart', 'ollama.service'], timeout=180)
    run(['systemctl', 'start', 'ai-gateway.service'])
    for attempt in range(60):
        try:
            e.runtime(BASE, e.config(), baseline)
            break
        except Exception:
            if attempt == 59:
                raise
            time.sleep(1)
    e.resume_ingress(baseline)
    e.write_once(directory / 'runtime-restored.json', {
        'source_sha': sha, 'release': BASE.name, 'snapshot': snapshot_hash,
        'reason': 'stalled development model probe; no Stage F cutover',
        'model_inference': 'PENDING separate bounded probe'})


def repair_baseline(state, sha):
    require_kernel_clear()
    previous = e.CURRENT.resolve()
    require(previous.name.startswith('stage-f-'))
    previous_sha = verify_release(previous)['source_git_sha']
    previous_state = STATE / previous_sha
    original = e.read(previous_state / 'baseline.json')
    recovery, manifest = verify_snapshot(previous_state, original)
    require_no_media_workers()
    e.quiesce(original, allow_gateway_unavailable=True)
    e.require_hermes_stopped()
    e.comfy_idle()
    e.clients()
    state.mkdir(mode=0o700)
    copied = state / 'hermes-recovery'
    shutil.copytree(recovery, copied)
    # Earlier snapshots archived these binaries but did not list standalone
    # copies. Recover exact bytes/stat from the checksum-verified archive.
    copied.chmod(0o700)
    with tarfile.open(copied / 'config-state-integration.tar') as archive:
        for path in MANAGED_FILES:
            binary = str(path)
            if binary in manifest['files']:
                continue
            category = 'bin' if path.parent == Path('/usr/local/bin') else 'libexec'
            member = archive.getmember('integration/' + category + '/' + path.name)
            target = copied / ('original-' + path.name)
            target.write_bytes(archive.extractfile(member).read())
            target.chmod(0o400)
            manifest['files'][binary] = {'copy': target.name, 'sha256': e.digest(target),
                'mode': member.mode, 'uid': member.uid, 'gid': member.gid}
            manifest['archives'][target.name] = e.digest(target)
    atomic_restore(copied / 'manifest.json', json.dumps(manifest, sort_keys=True).encode(), 0o400, 0, 0)
    copied.chmod(0o500)
    return {**original, 'source_sha': sha, 'previous_candidate': str(previous),
            'hermes_snapshot': e.digest(copied / 'manifest.json')}


def main(step):
    sha = e.git_run(['rev-parse', 'HEAD'])
    candidate = Path('/opt/ai-platform/releases') / ('stage-f-' + sha[:12])
    state = STATE / sha
    if step == '00_preflight':
        preflight()
        return
    require(os.geteuid() == 0)
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if step == '40_rollback' and not state.exists():
            recover_unmodified_baseline(sha)
            return
        if step == '10_build_install':
            require(not state.exists() and not candidate.exists())
            if e.CURRENT.resolve() != BASE:
                baseline = repair_baseline(state, sha)
            else:
                preflight()
                state.mkdir(mode=0o700)
                baseline = {'source_sha': sha, 'rollback': BASE.name, 'clients': e.clients(),
                    'comfy': e.identity('comfyui.service'), 'hermes_active': 'active',
                    'analysis_timer_active': run(['systemctl', 'show', 'ai-bridge-analysis.timer', '-p', 'ActiveState', '--value']),
                    'rollback_checksums': e.digest(BASE / 'metadata/SHA256SUMS')}
                baseline['hermes_snapshot'] = snapshot(state)
            e.write_once(state / 'baseline.json', baseline)
            run(['bash', ROOT / 'deploy/stage-f/build_release.sh', candidate, candidate.name],
                timeout=1800, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            require(verify_release(candidate)['source_git_sha'] == sha)
            e.write_once(state / 'installed.json', {'checksums': e.digest(candidate / 'metadata/SHA256SUMS'),
                'plugin_hashes': {p: e.digest(candidate / 'services/ai-bridge/integrations/hermes/ai-platform-messaging' / p)
                                  for p in ('__init__.py', 'plugin.yaml')}})
            return
        baseline = e.read(state / 'baseline.json')
        require(baseline['source_sha'] == sha and baseline['rollback'] == BASE.name)
        require(e.digest(BASE / 'metadata/SHA256SUMS') == baseline['rollback_checksums'])
        verify_snapshot(state, baseline)
        if step != '40_rollback':
            require(e.digest(candidate / 'metadata/SHA256SUMS') == e.read(state / 'installed.json')['checksums'])
        if step in ('20_cutover', '40_rollback', '60_reactivate'):
            if step == '60_reactivate':
                require((state / 'rollback-smoke.json').is_file())
            switch(BASE if step == '40_rollback' else candidate, candidate, state, baseline)
            if not (state / (step + '.json')).exists():
                e.write_once(state / (step + '.json'), {'time': time.time()})
        elif step in ('30_smoke', '50_rollback_smoke', '70_reactivate_smoke'):
            phase, target, prerequisite = {
                '30_smoke': ('candidate-smoke', candidate, '20_cutover'),
                '50_rollback_smoke': ('rollback-smoke', BASE, '40_rollback'),
                '70_reactivate_smoke': ('final-smoke', candidate, '60_reactivate')}[step]
            require((state / (prerequisite + '.json')).is_file())
            smoke(phase, target, candidate, state, baseline)
        elif step == '90_finalize':
            for phase, target in (('candidate-smoke', candidate), ('rollback-smoke', BASE), ('final-smoke', candidate)):
                evidence = e.read(state / (phase + '.json'))
                require(evidence['release'] == target.name)
                require(e.read(Path(evidence['evidence']) / 'pass.json')['compatibility'] == 'PASS')
            e.runtime(candidate, e.config(), baseline)
            e.hermes_state()
            require(not hermes_git(['status', '--porcelain']))
            e.write_once(state / 'complete.json', {'source_sha': sha, 'internal_e2e': 'PASS', 'external_transport': 'DEFERRED/NOT TESTED'})
        else:
            raise ValueError('unknown step')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except BaseException as error:
        frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == __file__]
        print('GATE_FAIL=' + type(error).__name__ + ' location=' + '/'.join(f'{f.name}:{f.lineno}' for f in frames), file=sys.stderr)
        raise SystemExit(1)
    print('PASS: Stage F ' + sys.argv[1])
