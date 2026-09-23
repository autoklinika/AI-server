#!/usr/bin/env python3
"""Stage G controller: unchanged GPU/messaging integration, reversible release switch."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('stage_f_runtime', ROOT / 'deploy/stage-f/autopilot/gate.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
e, run, require = f.e, f.run, f.require
BASE = Path('/opt/ai-platform/releases/stage-f-d8f68cadd953')
BASE_SHA = 'd8f68cadd95372b5a9adc75ef6450719af437850'
STATE = Path('/var/lib/ai-platform/stage-g')
f.STATE = STATE


def verify(path):
    stage = dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())['stage'].lower()
    require(stage in ('f', 'g'))
    return e.verify_release(path, stage)


def clients():
    # All installed clients/plugin/provider extensions must remain byte-identical.
    current = e.CURRENT.resolve()
    previous = e.D6
    e.D6 = current
    try:
        result = f._original_clients()
    finally:
        e.D6 = previous
    for actual, relative in f.MANAGED_FILES.items():
        require(actual.read_bytes() == (current / 'services/ai-bridge' / relative).read_bytes())
    require(f.COMFY_EXTENSION.read_bytes() == (current / 'services/ai-bridge/deploy/comfyui/ai_platform_residency.py').read_bytes())
    for name in ('__init__.py', 'plugin.yaml'):
        require((f.PLUGIN / name).read_bytes() == (current / 'services/ai-bridge/integrations/hermes/ai-platform-messaging' / name).read_bytes())
    require(not f.hermes_git(['status', '--porcelain']))
    return result


e.clients = clients
e.runtime = f._original_runtime


def history(target, baseline=None, freshness=False):
    env = dict(os.environ)
    for token in shlex.split(run(['systemctl', 'show', 'ai-bridge.service', '-p', 'Environment', '--value'])):
        if token.startswith('AI_BRIDGE_'):
            key, value = token.split('=', 1)
            env[key] = value
    user = run(['systemctl', 'show', 'ai-bridge.service', '-p', 'User', '--value'])
    require(bool(user) and user != 'root')
    command = ['runuser', '-u', user, '--', target / 'services/ai-bridge/.venv/bin/python',
               ROOT / 'deploy/stage-g/domain_probe.py']
    if baseline is not None:
        command += ['--baseline', '-']
    if freshness:
        command += ['--freshness']
    return json.loads(run(command, timeout=1200, env=env, cwd=target / 'services/ai-bridge',
                          input=json.dumps(baseline) if baseline is not None else None))


def preflight():
    require(e.CURRENT.resolve() == BASE)
    require(verify(BASE)['source_git_sha'] == BASE_SHA)
    f.require_kernel_clear()
    e.runtime(BASE, e.config())
    e.require_hermes_stopped()
    require(e.fetch(e.GATEWAY + '/status')['gpu_residency']['state'] == 'llm')
    f.require_no_media_workers()


def switch(target, state, baseline):
    verify(target)  # Rollback never needs candidate validation or health.
    e.quiesce(baseline, allow_gateway_unavailable=target == BASE)
    e.require_hermes_stopped()
    f.require_no_media_workers()
    e.comfy_idle()
    f.require_kernel_clear()
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge.service'])
    f.recover_gpu_quiesced(state)
    temporary = e.CURRENT.with_name('.stage-g-' + uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, e.CURRENT)
    run(['systemctl', 'start', 'ai-gateway.service', 'ai-bridge.service'])
    for attempt in range(60):
        try:
            e.runtime(target, e.config(), baseline)
            break
        except Exception:
            if attempt == 59:
                raise
            time.sleep(1)
    require(e.identity('ollama.service') == baseline['ollama'])
    history(target, baseline['history'])
    e.resume_ingress(baseline)


def smoke_body(phase, target, candidate, state, baseline):
    e.runtime(target, e.config(), baseline)
    before = [e.identity(u) for u in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service', 'ollama.service')]
    evidence_dir = state / (phase + '-' + uuid4().hex)
    evidence_dir.mkdir(mode=0o700)
    e.api_smoke(e.config())
    e.wvc_smoke()
    e.hermes_oneshot_smoke(keep_ingress_paused=True)
    harness = e.load_module('stage_g_compat_harness', ROOT / 'deploy/stage-f/internal_e2e.py')
    f.messaging_boundary_smoke(harness.configured_hermes_model(f.CONFIG))
    domain = history(target, baseline['history'], freshness=target != BASE)
    e.write_once(evidence_dir / 'domain.json', domain)
    print('DOMAIN_EVIDENCE=' + json.dumps(domain, sort_keys=True), flush=True)
    e.quiesce(baseline)
    e.require_hermes_stopped()
    try:
        name, uid, home = e.hermes_account()
        with tempfile.TemporaryDirectory(prefix='stage-g-internal-') as temporary:
            os.chown(temporary, uid, f.HERMES.stat().st_gid)
            output = Path(temporary) / 'internal.json'
            command = ['runuser', '-u', name, '--', 'env', f'HOME={home}', f'PYTHONPATH={f.SOURCE}',
                       f.SOURCE / 'venv/bin/python', ROOT / 'deploy/stage-f/internal_e2e.py', '--media', '--output', output]
            with (evidence_dir / 'harness.log').open('x') as log:
                completed = subprocess.run([str(a) for a in command], stdout=log, stderr=subprocess.STDOUT, timeout=10800)
            require(completed.returncode == 0)
            evidence = e.read(output)
            require(evidence['status'] == 'PASS' and len(evidence['media']) == 4)
            require(evidence['external_transport'] == 'DEFERRED/NOT TESTED')
            e.write_once(evidence_dir / 'internal.json', evidence)
    finally:
        e.runtime(target, e.config(), baseline)
        e.resume_ingress(baseline)
    e.wvc_smoke()
    e.runtime(target, e.config(), baseline)
    e.require_hermes_stopped()
    require(before == [e.identity(u) for u in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service', 'ollama.service')])
    require(e.identity('ollama.service') == baseline['ollama'])
    e.write_once(evidence_dir / 'provisional.json', {'release': target.name, 'time': time.time(), 'phase': phase,
        'compatibility': 'PASS', 'internal_e2e': 'PASS', 'external_transport': 'DEFERRED/NOT TESTED'})
    return {'evidence': str(evidence_dir), 'release': target.name}


f._smoke = smoke_body


def paused_gpu_rollback():
    """Restore verified service bytes after a kernel fault, never probe the GPU.

    This is containment, not a passing smoke or permission to resume inference.
    The fault marker and residency latch remain intact across the release switch.
    """
    marker = e.read(STATE / 'gpu-blocked.json')
    require(marker['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    require(e.CURRENT.resolve() in (BASE, Path(marker['release'])))
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service'], timeout=180)
    e.user_systemctl(['stop', 'hermes-gateway.service'])
    e.require_hermes_stopped()
    f.require_no_media_workers()
    require(verify(BASE)['source_git_sha'] == BASE_SHA)
    before = str(e.CURRENT.resolve())
    run(['systemctl', 'stop', 'ai-bridge.service'])
    temporary = e.CURRENT.with_name('.stage-g-contained-' + uuid4().hex)
    temporary.symlink_to(BASE)
    os.replace(temporary, e.CURRENT)
    run(['systemctl', 'start', 'ai-bridge.service'])
    for attempt in range(30):
        try:
            require(e.fetch(e.bridge_health_url())['status'] == 'ok')
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    clients()
    for unit in ('ai-gateway.service', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service'):
        require(run(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']) == 'inactive')
    e.require_hermes_stopped()
    e.write_once(STATE / ('contained-rollback-' + uuid4().hex + '.json'), {
        'status': 'BLOCKED_GPU', 'before': before, 'restored': str(BASE), 'time': time.time(),
        'gpu_probes': 'NOT RUN', 'ingress': 'PAUSED', 'history': history(BASE),
        'acceptance_smoke': 'NOT RUN: kernel fault', 'fault_marker_preserved': (STATE / 'gpu-blocked.json').exists()})
    return 'BLOCKED_GPU'


def main(step):
    sha = e.git_run(['rev-parse', 'HEAD'])
    candidate = Path('/opt/ai-platform/releases') / ('stage-g-' + sha[:12])
    state = STATE / sha
    require(os.geteuid() == 0)
    if step == '40_rollback' and (STATE / 'gpu-blocked.json').exists():
        marker = e.read(STATE / 'gpu-blocked.json')
        if marker['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            with (STATE / 'executor.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return paused_gpu_rollback()
    if step == '00_preflight':
        recovery = e.load_module('stage_g_cold_recovery', ROOT / 'deploy/stage-g/cold_recovery.py')
        recovery.recover_if_needed(sys.modules[__name__])
        preflight()
        isolated = e.load_module('stage_g_isolated_video', ROOT / 'deploy/stage-g/isolated_video.py')
        isolated.validate(sys.modules[__name__])
        return
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if step == '10_build_install':
            preflight()
            require(not state.exists() and not candidate.exists())
            state.mkdir(mode=0o700)
            baseline = {'source_sha': sha, 'rollback': str(BASE), 'clients': clients(),
                'comfy': e.identity('comfyui.service'), 'ollama': e.identity('ollama.service'),
                'hermes_active': 'inactive', 'history': history(BASE),
                'analysis_timer_active': run(['systemctl', 'show', 'ai-bridge-analysis.timer', '-p', 'ActiveState', '--value']),
                'rollback_checksums': e.digest(BASE / 'metadata/SHA256SUMS')}
            e.write_once(state / 'baseline.json', baseline)
            run(['bash', ROOT / 'deploy/stage-g/build_release.sh', candidate, candidate.name], timeout=1800,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            require(verify(candidate)['source_git_sha'] == sha)
            e.write_once(state / 'installed.json', {'checksums': e.digest(candidate / 'metadata/SHA256SUMS')})
            return
        baseline = e.read(state / 'baseline.json')
        require(baseline['source_sha'] == sha and baseline['rollback'] == str(BASE))
        require(e.digest(BASE / 'metadata/SHA256SUMS') == baseline['rollback_checksums'])
        if step != '40_rollback':
            require(e.digest(candidate / 'metadata/SHA256SUMS') == e.read(state / 'installed.json')['checksums'])
        if step in ('20_cutover', '40_rollback', '60_reactivate'):
            if step == '60_reactivate':
                require((state / 'rollback-smoke.json').is_file())
            switch(BASE if step == '40_rollback' else candidate, state, baseline)
            e.write_once(state / (step + '.json'), {'time': time.time()})
        elif step in ('30_smoke', '50_rollback_smoke', '70_reactivate_smoke'):
            phase, target, prerequisite = {'30_smoke': ('candidate-smoke', candidate, '20_cutover'),
                '50_rollback_smoke': ('rollback-smoke', BASE, '40_rollback'),
                '70_reactivate_smoke': ('final-smoke', candidate, '60_reactivate')}[step]
            require((state / (prerequisite + '.json')).is_file())
            f.smoke(phase, target, candidate, state, baseline)
        elif step == '90_finalize':
            for phase, target in (('candidate-smoke', candidate), ('rollback-smoke', BASE), ('final-smoke', candidate)):
                evidence = e.read(state / (phase + '.json'))
                require(evidence['release'] == target.name)
                require(e.read(Path(evidence['evidence']) / 'pass.json')['compatibility'] == 'PASS')
            e.runtime(candidate, e.config(), baseline)
            e.require_hermes_stopped()
            evidence = history(candidate, baseline['history'])
            e.write_once(state / 'complete.json', {'source_sha': sha, 'history': evidence,
                'internal_e2e': 'PASS', 'external_transport': 'DEFERRED/NOT TESTED'})
            print('HISTORY_PRESERVED=' + json.dumps(evidence, sort_keys=True))
        else:
            raise ValueError('unknown step')


if __name__ == '__main__':
    try:
        outcome = main(sys.argv[1])
    except BaseException as error:
        frames = [f for f in traceback.extract_tb(error.__traceback__) if str(ROOT / 'deploy') in f.filename]
        print('GATE_FAIL=' + type(error).__name__ + ' location=' + '/'.join(f'{Path(f.filename).name}:{f.name}:{f.lineno}' for f in frames), file=sys.stderr)
        raise SystemExit(1)
    print('BLOCKED_GPU: verified F restored; ingress remains paused; no GPU probes' if outcome == 'BLOCKED_GPU' else 'PASS: Stage G ' + sys.argv[1])
