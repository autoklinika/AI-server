#!/usr/bin/env python3
"""Stage H: reversible legacy quarantine with the accepted G safety gates."""
import fcntl
import importlib.util
import json
import os
import re
from pathlib import Path
import sys
import time
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('stage_h_g_primitives', ROOT / 'deploy/stage-g/autopilot/gate.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
e, f, run, require = g.e, g.f, g.run, g.require
BASE = Path('/opt/ai-platform/releases/stage-g-fa6b31e5f7dc')
BASE_SHA = 'fa6b31e5f7dcc7a67fe1928e7bf099f2256225c2'
STATE = Path('/var/lib/ai-platform/stage-h')
q = e.load_module('stage_h_quarantine', ROOT / 'deploy/stage-h/quarantine.py')
audit = e.load_module('stage_h_audit', ROOT / 'deploy/stage-h/audit.py')
g.BASE, g.BASE_SHA, g.STATE, f.STATE = BASE, BASE_SHA, STATE, STATE


def verify(path):
    stage = dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())['stage'].lower()
    require(stage in ('f', 'g', 'h'))
    return e.verify_release(path, stage)


g.verify = verify


def deployment_sha(step, head):
    pointer = STATE / 'deployment.json'
    if step == '40_rollback' and pointer.exists():
        sha = e.read(pointer)['source_sha']
        require(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha))
        return sha
    return head


def reference_audit(destination):
    report = audit.collect(g, q)
    e.write_once(destination, report)
    require(not report['blockers'])
    print('REFERENCE_AUDIT=PASS worktrees=' + str(len(report['worktrees'])) +
          ' releases=' + str(len(report['releases'])) + ' blockers=0', flush=True)
    return report


def resume_analysis_timer():
    require(run(['systemctl', 'is-enabled', 'ai-bridge-analysis.timer']) == 'enabled')
    run(['systemctl', 'start', 'ai-bridge-analysis.timer'])
    require(run(['systemctl', 'show', 'ai-bridge-analysis.timer',
                 '-p', 'ActiveState', '--value']) == 'active')
    return {'enabled': 'enabled', 'active': 'active'}


def reconcile_accepted_runtime():
    current = e.CURRENT.resolve(strict=True)
    stamp = verify(current)
    release = dict(line.split('=', 1) for line in
                   (current / 'RELEASE').read_text().splitlines())
    require(release['stage'].lower() == 'h')
    source_sha = stamp['source_git_sha']
    accepted = e.read(STATE / source_sha / 'complete.json')
    require(accepted['source_sha'] == source_sha)
    timer = resume_analysis_timer()
    return {'release': current.name, 'source_sha': source_sha, 'analysis_timer': timer}


def kernel_contain():
    record = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'status': 'BLOCKED_GPU', 'release': str(e.CURRENT.resolve()), 'time': time.time()}
    temporary = STATE / ('gpu-blocked-' + uuid4().hex)
    temporary.write_text(json.dumps(record))
    os.replace(temporary, STATE / 'gpu-blocked.json')
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service'], timeout=180)
    e.user_systemctl(['stop', 'hermes-gateway.service'])


def preflight():
    require(e.CURRENT.resolve() == BASE)
    require(verify(BASE)['source_git_sha'] == BASE_SHA)
    f.require_kernel_clear()
    e.require_hermes_stopped()
    f.require_no_media_workers()
    e.runtime(BASE, e.config())
    require(run(['systemctl', 'show', 'ai-bridge-analysis.timer', '-p', 'ActiveState', '--value']) == 'inactive')
    # H cannot start on a provisional G release or merely passing local tests.
    accepted = e.read(Path('/var/lib/ai-platform/stage-g') / BASE_SHA / 'complete.json')
    require(accepted['source_sha'] == BASE_SHA)


def switch(target, state, baseline, manifest, restore):
    verify(target)
    e.quiesce(baseline, allow_gateway_unavailable=restore)
    e.require_hermes_stopped()
    f.require_no_media_workers()
    f.require_kernel_clear()
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge.service'])
    watch = e.load_module('stage_h_switch_watch', ROOT / 'deploy/stage-f/gpu_watch.py')
    with watch.KernelGuard(run, kernel_contain, state / ('switch-kernel-' + uuid4().hex + '.log')) as guard:
        f.recover_gpu_quiesced(state)
        reference_audit(state / ('references-before-' + uuid4().hex + '.json'))
        guard.check()
        q.relocate(manifest, restore=restore)
        temporary = e.CURRENT.with_name('.stage-h-' + uuid4().hex)
        temporary.symlink_to(target)
        os.replace(temporary, e.CURRENT)
        run(['systemctl', 'start', 'ai-gateway.service', 'ai-bridge.service'])
        for attempt in range(60):
            guard.check()
            try:
                e.runtime(target, e.config(), baseline)
                break
            except Exception:
                if attempt == 59:
                    raise
                time.sleep(1)
        require(e.identity('ollama.service') == baseline['ollama'])
        g.history(target, baseline['history'])
        q.verify(manifest, restored=restore)
        reference_audit(state / ('references-after-' + uuid4().hex + '.json'))
        e.require_hermes_stopped()


def paused_rollback(state):
    # Kernel fault recovery is containment only: no GPU API, no latch clearing.
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service'], timeout=180)
    e.user_systemctl(['stop', 'hermes-gateway.service'])
    e.require_hermes_stopped()
    f.require_no_media_workers()
    require(verify(BASE)['source_git_sha'] == BASE_SHA)
    manifest_path = state / 'quarantine.json'
    if manifest_path.exists():
        q.relocate(e.read(manifest_path), restore=True)
    run(['systemctl', 'stop', 'ai-bridge.service'])
    temporary = e.CURRENT.with_name('.stage-h-contained-' + uuid4().hex)
    temporary.symlink_to(BASE)
    os.replace(temporary, e.CURRENT)
    run(['systemctl', 'start', 'ai-bridge.service'])
    e.write_once(STATE / ('contained-' + uuid4().hex + '.json'), {
        'status': 'BLOCKED_GPU', 'restored': str(BASE), 'ingress': 'PAUSED',
        'gpu_probes': 'NOT RUN', 'physical_power_cycle': 'REQUIRED', 'reboot': 'PROHIBITED'})
    return 'BLOCKED_GPU'


def main(step):
    require(os.geteuid() == 0)
    head = e.git_run(['rev-parse', 'HEAD'])
    sha = deployment_sha(step, head)
    candidate = Path('/opt/ai-platform/releases') / ('stage-h-' + sha[:12])
    state = STATE / sha
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = STATE / 'gpu-blocked.json'
        if marker.exists() and e.read(marker)['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            require(step == '40_rollback')
            return paused_rollback(state)
        if step == '00_preflight':
            preflight()
            reference_audit(STATE / ('preflight-' + uuid4().hex + '.json'))
            return
        if step == '90_finalize' and e.CURRENT.resolve() != candidate:
            result = reconcile_accepted_runtime()
            print('PRODUCTION_RECONCILE=PASS release=' + result['release'] +
                  ' analysis_timer=active', flush=True)
            return
        if step == '10_build_install':
            preflight()
            require(not state.exists() and not candidate.exists())
            state.mkdir(mode=0o700)
            reference_audit(state / 'references-original.json')
            manifest = q.plan(candidate.name)
            e.write_once(state / 'quarantine.json', manifest)
            baseline = {'source_sha': sha, 'rollback': str(BASE), 'clients': g.clients(),
                'comfy': e.identity('comfyui.service'), 'ollama': e.identity('ollama.service'),
                'hermes_active': 'inactive', 'analysis_timer_active': 'inactive',
                'history': g.history(BASE), 'rollback_checksums': e.digest(BASE / 'metadata/SHA256SUMS'),
                'quarantine_manifest_sha256': e.digest(state / 'quarantine.json')}
            e.write_once(state / 'baseline.json', baseline)
            run(['bash', ROOT / 'deploy/stage-h/build_release.sh', candidate, candidate.name], timeout=1800,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            require(verify(candidate)['source_git_sha'] == sha)
            e.write_once(state / 'installed.json', {'checksums': e.digest(candidate / 'metadata/SHA256SUMS')})
            return
        baseline, manifest = e.read(state / 'baseline.json'), e.read(state / 'quarantine.json')
        require(baseline['source_sha'] == sha and baseline['rollback'] == str(BASE))
        require(e.digest(state / 'quarantine.json') == baseline['quarantine_manifest_sha256'])
        require(e.digest(BASE / 'metadata/SHA256SUMS') == baseline['rollback_checksums'])
        if step != '40_rollback':
            require(e.digest(candidate / 'metadata/SHA256SUMS') == e.read(state / 'installed.json')['checksums'])
        if step in ('20_cutover', '40_rollback', '60_reactivate'):
            if step == '60_reactivate':
                require((state / 'rollback-smoke.json').is_file())
            restore = step == '40_rollback'
            if step == '20_cutover':
                pointer = STATE / ('deployment-' + uuid4().hex)
                e.write_once(pointer, {'source_sha': sha})
                os.replace(pointer, STATE / 'deployment.json')
                q.sync_directory(STATE)
            switch(BASE if restore else candidate, state, baseline, manifest, restore)
            receipt = step + '.json'
            if restore and (state / receipt).exists():
                receipt = 'recovery-rollback-' + uuid4().hex + '.json'
            e.write_once(state / receipt, {'time': time.time(), 'restored': restore,
                                         'controller_sha': head, 'deployment_sha': sha})
        elif step in ('30_smoke', '50_rollback_smoke', '70_reactivate_smoke'):
            phase, target, prerequisite = {'30_smoke': ('candidate-smoke', candidate, '20_cutover'),
                '50_rollback_smoke': ('rollback-smoke', BASE, '40_rollback'),
                '70_reactivate_smoke': ('final-smoke', candidate, '60_reactivate')}[step]
            require((state / (prerequisite + '.json')).is_file())
            q.verify(manifest, restored=target == BASE)
            f.smoke(phase, target, candidate, state, baseline)
            q.verify(manifest, restored=target == BASE)
        elif step == '90_finalize':
            for phase, target in (('candidate-smoke', candidate), ('rollback-smoke', BASE), ('final-smoke', candidate)):
                evidence = e.read(state / (phase + '.json'))
                require(evidence['release'] == target.name)
                require(e.read(Path(evidence['evidence']) / 'pass.json')['compatibility'] == 'PASS')
            e.runtime(candidate, e.config(), baseline)
            e.require_hermes_stopped()
            q.verify(manifest)
            reference_audit(state / 'references-final.json')
            history = g.history(candidate, baseline['history'])
            timer = resume_analysis_timer()
            e.write_once(state / 'complete.json', {'source_sha': sha, 'history': history,
                'quarantined': [entry['source'] for entry in manifest['entries']],
                'restore_cycle': 'PASS', 'purge': 'NOT PERFORMED',
                'analysis_timer': timer,
                'external_transport': 'DEFERRED/NOT TESTED', 'physical_reconnect': 'NOT TESTED'})
        else:
            raise ValueError('unknown step')


if __name__ == '__main__':
    try:
        outcome = main(sys.argv[1])
    except BaseException as error:
        frames = [f for f in traceback.extract_tb(error.__traceback__) if str(ROOT / 'deploy') in f.filename]
        print('GATE_FAIL=' + type(error).__name__ + ' location=' + '/'.join(
            f'{Path(f.filename).name}:{f.name}:{f.lineno}' for f in frames), file=sys.stderr)
        raise SystemExit(1)
    print('BLOCKED_GPU: verified G restored; physical power-cycle required; no reboot' if outcome == 'BLOCKED_GPU'
          else 'PASS: Stage H ' + sys.argv[1])
