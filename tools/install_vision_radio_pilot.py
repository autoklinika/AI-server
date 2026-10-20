#!/usr/bin/env python3
"""Verify a pinned package; install and run the operator-authorized RADIO pilot.

Default --check is read-only. --pilot installs only the fixed executor, runs a
controlled candidate Gateway in process while the prior Gateway is stopped,
and restores the prior Gateway. It does NOT enable Vision in production.
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
import types
import secrets
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'deploy/vision-radio/BUNDLE_SHA256.json'
INSTALL = Path('/opt/ai-platform/vision-radio/releases')
UNIT = Path('/etc/systemd/system/ai-platform-radio.service')
STATE = Path('/var/lib/ai-platform-radio')
PYTHON = Path('/opt/ai-platform/current/services/ai-gateway/.venv/bin/python')


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def verified_files(root, manifest, digest):
    raw = manifest.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == digest, 'manifest digest mismatch')
    entries = json.loads(raw)
    require(type(entries) is dict and entries, 'invalid manifest')
    files = {}
    for name, expected in entries.items():
        path = Path(name)
        require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
                'unsafe manifest path')
        target = root / path
        require(not target.is_symlink() and target.resolve().is_relative_to(root.resolve()), 'source escapes package')
        content = target.read_bytes()
        require(hashlib.sha256(content).hexdigest() == expected, 'source changed: ' + name)
        files[name] = content
    require('tools/install_vision_radio_pilot.py' in files and
            files['tools/install_vision_radio_pilot.py'] == Path(__file__).read_bytes(), 'installer not pinned')
    return files


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=35)
    require(p.returncode == 0, 'system command failed: ' + args[0] + ': ' + ' '.join(p.stderr.split())[:500])
    return p.stdout.strip()


def verify_runtime_link(module):
    # ProtectHome exposes the canonical Python tree, not aliases elsewhere in
    # the home directory. Check this before attempting a systemd launch.
    require((module.RUNTIME.parent / 'python3.11').readlink() == module.BASE_PYTHON / 'bin/python3.11',
            'Vision venv interpreter link must target the exposed canonical Python')


def worker_configuration_probe(files):
    """Real CPU exec as ai-vision with the exact transient sandbox, no GPU opens.

    Run before archiving any block. A failed probe leaves the old failure and
    global block intact, so the operator never starts inference on bad config.
    """
    module = types.ModuleType('_pinned_supervisor_config')
    module.__file__ = str(ROOT / 'deploy/vision-radio/radio_supervisor.py')
    exec(compile(files['deploy/vision-radio/radio_supervisor.py'], module.__file__, 'exec'), module.__dict__)
    worker = types.ModuleType('_pinned_worker_config')
    exec(compile(files['deploy/vision-radio/radio_worker.py'], 'pinned-radio-worker', 'exec'), worker.__dict__)
    verify_runtime_link(module)
    token = secrets.token_hex(16)
    unit = 'ai-radio-config-' + token + '.service'
    folder = STATE / ('config-probe-' + token)
    folder.mkdir(mode=0o750)
    os.chown(folder, 0, 972)
    folder.chmod(0o750)
    data = folder / 'data'
    data.mkdir(mode=0o750)
    os.chown(data, 994, 972)
    data.chmod(0o750)
    code = '''import os,socket,errno,sys,pathlib,json
assert os.getuid()==994 and pathlib.Path(sys.prefix).resolve()==pathlib.Path(sys.argv[2])
s=socket.socket(socket.AF_UNIX);s.close()
denied=0
for family in (socket.AF_INET,socket.AF_INET6):
 try: socket.socket(family)
 except OSError as e: denied+=int(e.errno in (errno.EAFNOSUPPORT,errno.EPERM,errno.EACCES))
assert denied==2
for p in ('/dev/kfd','/dev/dri/renderD128'): assert os.access(p,os.R_OK|os.W_OK)
for p in sys.argv[3:]:
 with open(p,'rb') as f: assert f.read(1)
with (pathlib.Path(sys.argv[1])/'cpu-proof.json').open('x') as f: json.dump({'uid':994,'inet_denied':True},f)
'''
    args = module.worker_command(unit, data, token)
    args = args[:args.index('--')] + ['--', str(module.RUNTIME), '-I', '-c', code,
                                     str(data), str(module.RUNTIME.parent.parent), str(worker.WEIGHTS), str(worker.IMAGE)]
    try:
        command(*args)
        deadline = time.monotonic() + 20
        while True:
            status = dict(line.split('=', 1) for line in command('systemctl', 'show', unit,
                '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainStatus').splitlines())
            if status.get('SubState') == 'exited':
                require(status == {'ActiveState': 'active', 'SubState': 'exited', 'Result': 'success',
                                   'ExecMainStatus': '0'}, 'CPU sandbox probe failed: ' + str(status))
                break
            require(status.get('ActiveState') not in ('failed', 'inactive') and time.monotonic() < deadline,
                    'CPU sandbox probe did not complete: ' + str(status))
            time.sleep(.1)
        require(json.loads((data / 'cpu-proof.json').read_text()) == {'uid': 994, 'inet_denied': True},
                'CPU probe proof missing')
        print(json.dumps({'worker_config_cpu_probe': 'PASS', 'gpu_inference': 'NOT_STARTED'}), flush=True)
    finally:
        # Only this unique, fixed CPU probe; never a model execution unit.
        command('systemctl', 'stop', unit)
        # A failed transient unit otherwise remains listed as failed and
        # blocks the next recovery. Its diagnostic journal is retained.
        status = command('systemctl', 'show', unit, '-p', 'ActiveState', '--value')
        if status == 'failed':
            command('systemctl', 'reset-failed', unit)
        shutil.rmtree(folder)


def install(files, digest, *, previous_unit=None):
    destination = INSTALL / digest[:16]
    # This first pilot intentionally refuses to replace an unknown installation.
    require(not destination.exists(), 'candidate version already exists')
    if previous_unit is None:
        require(not UNIT.exists(), 'existing executor installation requires review')
    else:
        require(UNIT.is_file() and UNIT.read_text() == previous_unit, 'previous executor changed after preflight')
    require(not (STATE / 'ownership.dirty').exists(), 'prior RADIO ownership unresolved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.parent.chmod(0o755)
    destination.parent.chmod(0o755)
    stage = destination.with_name(destination.name + '.building')
    require(not stage.exists(), 'stale package staging directory')
    stage.mkdir(mode=0o755)
    try:
        for name, content in files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(content)
            target.chmod(0o644)
        (stage / 'SOURCE_SHA256.json').write_text(json.dumps({name: hashlib.sha256(content).hexdigest()
            for name, content in files.items()}, sort_keys=True, indent=2) + '\n')
        for folder in (stage, *[p for p in stage.rglob('*') if p.is_dir()]):
            folder.chmod(0o755)
        os.rename(stage, destination)
    except BaseException:
        if stage.exists(): shutil.rmtree(stage)
        raise
    if STATE.exists():
        require(not STATE.is_symlink() and STATE.stat().st_uid == 0
                and not STATE.stat().st_mode & 0o022, 'untrusted existing executor state')
    STATE.mkdir(mode=0o710, exist_ok=True)
    os.chown(STATE, 0, 972)
    os.chmod(STATE, 0o710)
    sessions = STATE / 'sessions'
    if sessions.exists():
        require(not sessions.is_symlink() and sessions.stat().st_uid == 0
                and not sessions.stat().st_mode & 0o022, 'untrusted sessions directory')
    sessions.mkdir(mode=0o710, exist_ok=True)
    os.chown(sessions, 0, 972)
    sessions.chmod(0o710)
    content = files['deploy/vision-radio/ai-platform-radio.service'].decode().replace('@PACKAGE@', str(destination))
    pending = UNIT.with_name('.ai-platform-radio.service.staging')
    with pending.open('x') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    pending.chmod(0o644)
    os.replace(pending, UNIT)
    try:
        command('systemctl', 'daemon-reload')
        command('systemctl', 'start', 'ai-platform-radio.service')
    except BaseException:
        # Remove only the installation made by this exact invocation. Never
        # touch GPU markers, worker units or an existing production overlay.
        subprocess.run(['systemctl', 'stop', 'ai-platform-radio.service'], capture_output=True)
        if UNIT.read_text() == content:
            UNIT.unlink()
            if previous_unit is not None:
                with UNIT.open('x') as stream:
                    stream.write(previous_unit)
                UNIT.chmod(0o644)
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--resume-prelaunch', action='store_true',
                        help='Recover only the pinned failed root-Gateway attempt before any RADIO worker')
    parser.add_argument('--resume-launch-rejected', action='store_true',
                        help='Recover only the pinned systemd transient-property rejection before worker exec')
    args = parser.parse_args()
    require(not args.resume_prelaunch or args.pilot, 'resume-prelaunch requires pilot')
    require(not args.resume_launch_rejected or args.pilot, 'resume-launch-rejected requires pilot')
    require(not (args.resume_prelaunch and args.resume_launch_rejected), 'choose one recovery case')
    files = verified_files(ROOT, MANIFEST, args.manifest_sha256)
    result = {'source': 'SOURCE_SHA256_PASS', 'files': len(files), 'result': 'READY_FOR_OPERATOR_PILOT',
              'production_install': 'NOT_PERFORMED', 'n1_grant': 'NOT_ADMITTED'}
    if args.pilot:
        require(os.geteuid() == 0 and sys.stdin.isatty(), 'pilot requires interactive operator authorization')
        require(command('systemctl', 'is-active', 'ai-gateway.service') == 'active', 'Gateway not active')
        recovery = proof = None
        if args.resume_prelaunch or args.resume_launch_rejected:
            name = 'tools/vision_radio_recover_prelaunch.py'
            require(name in files, 'pinned recovery code missing')
            recovery = types.ModuleType('_pinned_radio_recovery')
            recovery.__file__ = str(ROOT / name)
            exec(compile(files[name], recovery.__file__, 'exec'), recovery.__dict__)
            if args.resume_launch_rejected:
                base = recovery
                name = 'tools/vision_radio_recover_launch_rejected.py'
                require(name in files, 'pinned launch recovery code missing')
                recovery = types.ModuleType('_pinned_launch_recovery')
                recovery.__file__ = str(ROOT / name)
                exec(compile(files[name], recovery.__file__, 'exec'), recovery.__dict__)
                recovery.base = base
            proof = recovery.preflight()
        STATE.mkdir(mode=0o710, exist_ok=True)
        require(not STATE.is_symlink() and STATE.stat().st_uid == 0 and not STATE.stat().st_mode & 0o022,
                'untrusted executor state before CPU probe')
        os.chown(STATE, 0, 972)
        STATE.chmod(0o710)
        worker_configuration_probe(files)
        if proof is not None and args.resume_launch_rejected:
            recovery.archive_ownership(proof)
        destination = install(files, args.manifest_sha256,
                              previous_unit=None if proof is None else proof['previous_unit'])
        pilot = destination / 'tools/vision_radio_hardware_pilot.py'
        try:
            if proof is not None:
                print(json.dumps(recovery.archive_and_restore(proof), sort_keys=True), flush=True)
            p = subprocess.run([str(PYTHON), '-I', str(pilot)], timeout=420)
            return p.returncode
        finally:
            # Stop only the supervisor after the pilot, not its owned worker
            # cgroups on uncertainty. Ownership marker and RuntimeMaxSec remain.
            subprocess.run(['systemctl', 'stop', 'ai-platform-radio.service'], capture_output=True, timeout=30)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
