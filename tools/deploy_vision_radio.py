#!/usr/bin/env python3
"""Pinned Vision activation on the existing production Gateway. Default: check.

Apply tests the exact backported source on GPU, cutover, rollback, then final
activation. It preserves Stage O, the old overlay and every GPU dirty marker.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'deploy/vision-radio/PRODUCTION_SHA256.json'
OLD = Path('/opt/ai-platform/gateway-overlays/rm-engine-adapters-v1-0016bbe-hwpass')
EXECUTOR_SHA = '7cec662df1089831571ef0184b2e256a56579100cba8e478bfa310fb2df2b0fe'
EXECUTOR = Path('/opt/ai-platform/vision-radio/releases') / EXECUTOR_SHA[:16]
EXECUTOR_UNIT = Path('/etc/systemd/system/ai-platform-radio.service')
STATE = Path('/var/lib/ai-platform-radio')
DROPIN = Path('/etc/systemd/system/ai-gateway.service.d/99-vision-radio.conf')
PYTHON = Path('/opt/ai-platform/current/services/ai-gateway/.venv/bin/python')
PATCH = 'deploy/vision-radio/gateway-production.patch'
SOURCE = 'deploy/vision-radio/GATEWAY_PRODUCTION_SOURCE_SHA256.json'
ALLOWED = {'src/ai_bridge/' + p for p in (
    'settings.py', 'gateway/app.py', 'gateway/admission.py', 'gateway/engine_state.py',
    'gateway/resource_leases.py', 'gateway/vision_lifecycle.py', 'gateway/vision_radio_client.py',
    'providers/registry.py', 'providers/accelerators.py')}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=40)
    require(p.returncode == 0, args[0] + ': ' + ' '.join(p.stderr.split())[:300])
    return p.stdout.strip()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def verified_files(expected):
    raw = MANIFEST.read_bytes()
    require(digest(raw) == expected, 'production manifest changed')
    files = {}
    for name, sha in json.loads(raw).items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'invalid package path')
        p = ROOT / relative
        require(not p.is_symlink() and p.resolve().is_relative_to(ROOT.resolve()), 'package path escapes')
        content = p.read_bytes()
        require(digest(content) == sha, 'package source changed: ' + name)
        files[name] = content
    require(files.get('tools/deploy_vision_radio.py') == Path(__file__).read_bytes(), 'deployer not pinned')
    return files


def module(files, name):
    m = types.ModuleType('_pinned_' + Path(name).stem)
    m.__file__ = str(ROOT / name)
    exec(compile(files[name], m.__file__, 'exec'), m.__dict__)
    return m


def trusted_file(path):
    require(not path.is_symlink(), 'unexpected root file symlink')
    for p in (path, *path.parents):
        info = p.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'root file is writable/untrusted')


def verify_executor():
    manifest = EXECUTOR / 'SOURCE_SHA256.json'
    trusted_file(manifest)
    require(digest(manifest.read_bytes()) == EXECUTOR_SHA, 'tested executor manifest changed')
    for name, sha in json.loads(manifest.read_text()).items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'invalid executor path')
        p = EXECUTOR / relative
        trusted_file(p)
        require(digest(p.read_bytes()) == sha, 'tested executor changed')
    trusted_file(EXECUTOR_UNIT)
    expected = (EXECUTOR / 'deploy/vision-radio/ai-platform-radio.service').read_text().replace('@PACKAGE@', str(EXECUTOR))
    require(EXECUTOR_UNIT.read_text() == expected, 'executor service is not the tested version')
    link = Path('/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-rocm714-py311/bin/python3.11')
    require(link.readlink() == Path('/home/harrypotter/.local/share/uv/python/cpython-3.11.16-linux-x86_64-gnu/bin/python3.11'),
            'tested interpreter link changed')


def validate_pilot(report):
    require(report.get('result') == 'GPU_PILOT_PASS' and report.get('prior_gateway_restored') is True
            and report.get('gateway_uid') == 1000, 'successful real GPU pilot required')
    rows = report.get('radio_inspections', [])
    require(len(rows) == 2 and all(row.get('execution_kind') == 'GPU_INFERENCE'
        and row.get('model') == 'anomalyvfm-radio' and row.get('pci_bdf') == '0000:c6:00.0'
        and row.get('weights_sha256') == '50a219ba436ed656ad3c0405f9e81df8ad00b2e715c98be66d7e2edb62a83a37'
        and row.get('map_shape') == [768, 768] for row in rows), 'GPU pilot evidence incomplete')


def build_tree(destination, files):
    """Reproduce the tested overlay, preserving all unrelated production bytes."""
    baseline = json.loads((OLD / 'SOURCE_SHA256.json').read_text())
    expected = json.loads(files[SOURCE])
    for line in files[PATCH].decode().splitlines():
        if line.startswith(('--- ', '+++ ')):
            name = line.split()[1]
            require(name == '/dev/null' or (name[:2] in ('a/', 'b/') and name[2:] in ALLOWED),
                    'patch touches a non-Vision path')
    require(set(baseline) <= set(expected) and set(expected) - set(baseline) <= ALLOWED,
            'unexpected production source inventory')
    for name, sha in baseline.items():
        require(name in ALLOWED or expected.get(name) == sha, 'unrelated production change: ' + name)
        p = OLD / name
        trusted_file(p)
        require(digest(p.read_bytes()) == sha, 'active baseline changed')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    with tempfile.NamedTemporaryFile() as patch:
        patch.write(files[PATCH]); patch.flush()
        command('/usr/bin/patch', '--batch', '--fuzz=0', '-p1', '-d', str(destination), '-i', patch.name)
    observed = {str(p.relative_to(destination)): digest(p.read_bytes())
                for p in destination.rglob('*') if p.is_file()}
    require(observed == expected, 'backport differs from tested source')
    return expected


def install(files, sha):
    destination = OLD.parent / ('vision-radio-' + sha[:16])
    require(not destination.exists(), 'deployment version already exists; use its rollback/check command')
    with tempfile.TemporaryDirectory(prefix='.vision-radio-', dir=OLD.parent) as tmp:
        stage = Path(tmp)
        source = build_tree(stage, files)
        for name, content in files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        target = stage / 'deploy/vision-radio/PRODUCTION_SHA256.json'
        raw = (json.dumps({name: digest(content) for name, content in files.items()}, sort_keys=True, indent=2) + '\n').encode()
        require(digest(raw) == sha, 'production manifest is not canonical')
        target.write_bytes(raw)
        (stage / 'SOURCE_SHA256.json').write_text(json.dumps(source, sort_keys=True, indent=2) + '\n')
        for path in (stage, *stage.rglob('*')):
            path.chmod(0o755 if path.is_dir() else 0o644)
        # TemporaryDirectory cleanup tolerates the renamed directory.
        os.rename(stage, destination)
    return destination


def override(destination):
    return ('# Vision RADIO on the existing Gateway RM.\n[Unit]\n'
        'Requires=ai-platform-radio.service\nAfter=ai-platform-radio.service\n[Service]\n'
        f'Environment="PYTHONPATH={destination}/src"\n'
        'Environment="AI_BRIDGE_GATEWAY_VISION_RADIO_ENABLED=true"\n')


def smoke(base, enabled):
    deadline = time.monotonic() + 35
    while True:
        try:
            base.current_idle()
            status = base.json_get('/status')
            vision = next(e for e in status['resource_manager']['engines'] if e['id'] == 'vision')
            require(vision['execution_available'] is enabled, 'unexpected Vision admission')
            require(base.json_get('/health')['status'] == 'ok', 'Gateway unhealthy')
            require(all(base.http_code(p) == 200 for p in ('/control/', '/api/v1/benchmarks', '/api/tags')),
                    'existing Gateway API smoke failed')
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(.25)


def switch(base, pilot, content):
    base.current_idle()
    require(not DROPIN.with_name('.99-vision-radio.conf.staging').exists(), 'stale override staging file')
    pilot.reserve_window()  # One existing scheduler; refuse a racing/queued job.
    command('systemctl', 'stop', 'ai-gateway.service')
    if content is None:
        DROPIN.unlink()
    else:
        pending = DROPIN.with_name('.99-vision-radio.conf.staging')
        try:
            with pending.open('x') as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            pending.chmod(0o644)
            os.replace(pending, DROPIN)
        finally:
            if pending.exists(): pending.unlink()
    command('systemctl', 'daemon-reload')
    command('systemctl', 'start', 'ai-gateway.service')
    smoke(base, content is not None)


def restore(base, content):
    # Startup/cutover failure must restore the prior source, preserving markers.
    if DROPIN.exists():
        require(DROPIN.read_text() == content, 'unknown override; automatic rollback refused')
    active = command('systemctl', 'show', 'ai-gateway.service', '-p', 'ActiveState', '--value')
    if active == 'active':
        snap = base.json_get('/status')
        require(snap.get('active_count') == 0 and snap.get('queued_count') == 0
                and snap.get('resource_leases', {}).get('lease_count') == 0,
                'rollback deferred: live work must complete first')
    command('systemctl', 'stop', 'ai-gateway.service')
    if DROPIN.exists(): DROPIN.unlink()
    command('systemctl', 'daemon-reload')
    command('systemctl', 'start', 'ai-gateway.service')
    command('systemctl', 'stop', 'ai-platform-radio.service')
    smoke(base, False)


def apply(files, sha, base):
    require(not DROPIN.exists(), 'Vision override already exists')
    trusted_file(STATE / 'PILOT_RESULT.json')
    validate_pilot(json.loads((STATE / 'PILOT_RESULT.json').read_text()))
    require(not (STATE / 'ownership.dirty').exists() and not (STATE / 'ownership.tmp').exists(),
            'prior worker ownership unresolved')
    enabled = subprocess.run(['systemctl', 'is-enabled', 'ai-platform-radio.service'],
                             capture_output=True, text=True, timeout=5)
    require(enabled.returncode == 1 and enabled.stdout.strip() == 'disabled',
            'unexpected executor boot state')
    destination = install(files, sha)
    content = override(destination)
    pilot = module(files, 'tools/vision_radio_hardware_pilot.py')
    committed = False
    try:
        command('systemctl', 'start', 'ai-platform-radio.service')
        # This exact backport must pass the real pilot before production cutover.
        p = subprocess.run([str(PYTHON), '-I', str(destination / 'tools/vision_radio_hardware_pilot.py')], timeout=420)
        require(p.returncode == 0, 'production candidate GPU pilot failed; old Gateway retained')
        validate_pilot(json.loads((STATE / 'PILOT_RESULT.json').read_text()))
        try:
            switch(base, pilot, content)
            switch(base, pilot, None)
            command('systemctl', 'stop', 'ai-platform-radio.service')
            smoke(base, False)
            command('systemctl', 'start', 'ai-platform-radio.service')
            switch(base, pilot, content)
            command('systemctl', 'enable', 'ai-platform-radio.service')
            committed = True
        except BaseException:
            restore(base, content)
            raise
    finally:
        if not committed and not DROPIN.exists():
            command('systemctl', 'stop', 'ai-platform-radio.service')
    return {'result': 'VISION_PRODUCTION_PASS', 'candidate_gpu_pilot': 'PASS', 'rollback_test': 'PASS',
            'production_install': 'PERFORMED', 'overlay': str(destination),
            'rollback_command': f'sudo /usr/bin/python3 -I {destination}/tools/deploy_vision_radio.py --rollback --manifest-sha256 {sha}'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    result = {'schema': 1, 'result': 'BLOCKED', 'gpu_reuse_safe': 'NOT_VERIFIED',
              'n1_grant': 'NOT_ADMITTED', 'comfyui_image_generation': 'NOT_TESTED'}
    try:
        files = verified_files(args.manifest_sha256)
        base = module(files, 'tools/deploy_rm_gateway_backport_v1.py')
        base.installed_overlay_ok()
        verify_executor()
        base.current_idle()
        if args.apply or args.rollback:
            require(os.geteuid() == 0 and sys.stdin.isatty(), 'interactive operator terminal required')
            if args.apply:
                result.update(apply(files, args.manifest_sha256, base))
            else:
                destination = OLD.parent / ('vision-radio-' + args.manifest_sha256[:16])
                content = override(destination)
                require(DROPIN.read_text() == content, 'unknown Vision override')
                pilot = module(files, 'tools/vision_radio_hardware_pilot.py')
                switch(base, pilot, None)
                command('systemctl', 'disable', 'ai-platform-radio.service')
                command('systemctl', 'stop', 'ai-platform-radio.service')
                smoke(base, False)
                result.update(result='VISION_ROLLBACK_PASS', production_install='ROLLED_BACK')
            (STATE / 'DEPLOY_RESULT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        else:
            with tempfile.TemporaryDirectory(prefix='vision-production-check-') as tmp:
                build_tree(Path(tmp), files)
            result.update(result='SOURCE_AND_HOST_PREFLIGHT_PASS', root_pilot_evidence='CHECKED_ONLY_ON_APPLY',
                          production_install='NOT_PERFORMED')
    except Exception as error:
        result['result'] = 'BLOCKED'
        result['error'] = type(error).__name__ + ': ' + str(error)[:300]
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)
    return 2 if result['result'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
