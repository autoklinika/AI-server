#!/usr/bin/env python3
"""Stage F supervisor gate. Private recovery material never leaves local storage."""
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
CONFIG = HERMES / 'config.yaml'
e.D6 = BASE  # Existing client fingerprints are identical in the E baseline.
require, run = e.require, e.run


def hermes_git(args):
    name, uid, home = e.hermes_account()
    return run(['runuser', '-u', name, '--', 'git', '-C', SOURCE, *args])


def verify_release(path):
    stage = dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())['stage'].lower()
    require(stage in ('e', 'f'))
    return e.verify_release(path, stage)


def preflight():
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
    paths = [CONFIG, *[SOURCE / p for p in PATCHED]]
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
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
            require(dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok')
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


def switch(target, candidate, state, baseline):
    rollback = target == BASE
    require(e.CURRENT.resolve() in (BASE, candidate))
    verify_release(target)
    require(e.clients() == baseline['clients'])
    e.quiesce(baseline, allow_gateway_unavailable=rollback)
    e.require_hermes_stopped()
    e.comfy_idle()
    # No ingress resume until both platform and matching Hermes configuration
    # validate. On any partial failure supervisor must invoke planned recovery.
    configure(candidate, state, baseline, rollback)
    run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge.service'])
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
    e.resume_ingress(baseline)


def smoke(phase, target, candidate, state, baseline):
    e.runtime(target, e.config(), baseline)
    before = [e.identity(u) for u in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')]
    evidence_dir = state / (phase + '-' + uuid4().hex)
    evidence_dir.mkdir(mode=0o700)
    e.api_smoke(e.config())
    e.wvc_smoke()
    e.hermes_oneshot_smoke()
    e.messaging_boundary_smoke()
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
        run(['bash', ROOT / 'deploy/stage-e/validate_media_runtime.sh', 'E'], timeout=1900)
        recovery, manifest = verify_snapshot(state, baseline)
        for path, info in manifest['files'].items():
            require(e.digest(path) == info['sha256'])
        require(not PLUGIN.exists())
    e.runtime(target, e.config(), baseline)
    e.hermes_state()
    require(before == [e.identity(u) for u in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')])
    e.write_once(evidence_dir / 'pass.json', {'release': target.name, 'time': time.time(), 'phase': phase,
        'compatibility': 'PASS', 'internal_e2e': 'PASS' if target == candidate else 'NOT APPLICABLE: E rollback',
        'external_transport': 'DEFERRED/NOT TESTED'})
    e.write_once(state / (phase + '.json'), {'evidence': str(evidence_dir), 'release': target.name})


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
    run(['systemctl', 'stop', 'ai-gateway.service'])
    run(['systemctl', 'restart', 'ollama.service'], timeout=90)
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
            preflight()
            require(not state.exists() and not candidate.exists())
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
