#!/usr/bin/env python3
"""Controlled-executor D.6 client transition; never activates a release.

The operator must quiesce ingress/analysis for the entire transition. Idle
observations are guards, not an admission lock. No credentials are read.
"""
import argparse
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import tempfile
import time

from observe_validation import fetch, snapshot
from validate_release_metadata import validate
from validate_rollback_readiness import verify_checksums

SNAPSHOT = Path('/srv/ai-data/platform/recovery/stage-d6-resource-manager-v2-20260922-r1-clients')
CURRENT = Path('/opt/ai-platform/current')
MAPPING = {
    '/usr/local/bin/hermes-foto-dispatch': ('tools/local_image/hermes_foto_dispatch_global.py', 0o755),
    '/usr/local/libexec/ai-server/hermes_resource_queue.py': ('tools/hermes_resource_queue.py', 0o644),
    '/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py': ('tools/local_image/hermes_foto_prompt_compiler.py', 0o644),
    '/usr/local/libexec/ai-server/hermes_video_dispatch.py': ('tools/local_video/hermes_video_dispatch_global.py', 0o755),
    '/usr/local/libexec/ai-server/qwen_prompt_compiler.py': ('tools/local_video/qwen_prompt_compiler.py', 0o644),
}
FIELDS = ['state', 'installed_sha256', 'candidate_sha256', 'installed_path', 'candidate_path']


def regular(path):
    # Reject symlink files and symlink ancestors; never follow a destination alias.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink in file path')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('not a regular file')
    return info


def capture(path):
    info = regular(path)
    return (path.read_bytes(), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def backup_bundle(root, manifest):
    root = root.resolve(strict=True)
    regular(manifest)
    if not manifest.resolve().is_relative_to(root):
        raise ValueError('manifest outside snapshot')
    with manifest.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != FIELDS:
            raise ValueError('unexpected snapshot manifest schema')
        rows = {}
        for row in reader:
            if None in row or None in row.values() or row['installed_path'] in rows:
                raise ValueError('malformed or duplicate manifest row')
            rows[row['installed_path']] = row
    bundle = {}
    for installed in MAPPING:
        row = rows.get(installed)
        if not row or row['state'] != 'DIFF' or not re.fullmatch('[0-9a-f]{64}', row['installed_sha256']):
            raise ValueError('required recovery identity missing')
        saved = capture(root / installed.lstrip('/'))
        if digest(saved[0]) != row['installed_sha256']:
            raise ValueError('backup checksum mismatch')
        # Ownership/mode come ONLY from original backup stat, never sanitized TSV.
        if saved[1] not in (0o644, 0o755) or saved[2:] != (0, 0):
            raise ValueError('unsafe backup metadata')
        bundle[installed] = saved
    # Historical inventory rows, candidate paths and r1 hashes are NOT inputs.
    return bundle


def candidate_bundle(release):
    validate(release)
    verify_checksums(release)
    covered = {line.split('  ', 1)[1].removeprefix('./')
               for line in (release / 'metadata/SHA256SUMS').read_text().splitlines()}
    bundle = {}
    for installed, (source, mode) in MAPPING.items():
        names = [f'services/{service}/{source}' for service in ('ai-bridge', 'ai-gateway')]
        if not all(name in covered for name in names):
            raise ValueError('client source absent from release checksums')
        copies = [capture(release / name)[0] for name in names]
        if copies[0] != copies[1]:
            raise ValueError('service client source mismatch')
        bundle[installed] = (copies[0], mode, 0, 0)
    return bundle


def atomic_install(path, saved):
    regular(path)
    data, mode, uid, gid = saved
    fd, name = tempfile.mkstemp(prefix='.d6-client-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)  # only an uninstalled temporary, never recovery evidence


class Runtime:
    def __init__(self, user):
        account = pwd.getpwnam(user)
        if account.pw_uid == 0:
            raise ValueError('Hermes must use its existing non-root user manager')
        self.user_command = ['runuser', '-u', user, '--', 'env',
                             f'XDG_RUNTIME_DIR=/run/user/{account.pw_uid}',
                             'systemctl', '--user']
        self.state = Path('/srv/ai-data/hermes/gateway_state.json')

    def command(self, args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()

    def identity(self, unit, user=False):
        command = self.user_command if user else ['systemctl']
        output = self.command(command + ['show', unit, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'InvocationID'])
        values = dict(line.split('=', 1) for line in output.splitlines())
        if values.get('ActiveState') != 'active' or int(values.get('MainPID', '0')) <= 0 or not values.get('InvocationID'):
            raise ValueError('service not active')
        return values['MainPID'], values['InvocationID']

    def guard(self, release):
        if CURRENT.resolve(strict=True) != release:
            raise ValueError('D.6 candidate must be active before either client transition')
        gateway = self.identity('ai-gateway.service')
        # A changed symlink alone does not prove the running Gateway uses D.6.
        if Path(f'/proc/{gateway[0]}/cwd').resolve(strict=True) != release / 'services/ai-gateway':
            raise ValueError('running Gateway is not the active D.6 release')
        result = snapshot(fetch)
        if any(result[k] for k in ('active', 'queued', 'leases', 'comfy_running', 'comfy_pending')):
            raise ValueError('Resource Manager or ComfyUI not idle')
        return gateway

    def restart(self, previous):
        before = self.state.stat().st_mtime_ns
        started = time.time_ns()
        self.command(self.user_command + ['restart', 'hermes-gateway.service'])
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                identity = self.identity('hermes-gateway.service', True)
                info = self.state.stat()
                data = json.loads(self.state.read_text())
                platforms = data.get('platforms') or {}
                if (identity != previous and info.st_mtime_ns > before and info.st_mtime_ns >= started
                        and data.get('gateway_state') == 'running'
                        and all((platforms.get(p) or {}).get('state') == 'connected'
                                for p in ('telegram', 'api_server'))):
                    return identity
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            time.sleep(1)
        raise ValueError('Hermes reconnect timeout')


def transition(action, release, old, new, runtime, destination=Path, install=atomic_install):
    """All inputs validated before mutation; caught failures restore entry state.

    Recovery requires idle and unchanged D.6/ComfyUI. If unsafe, leave evidence
    and return failure for the controlled executor, never force a live restore.
    """
    desired = new if action == 'apply' else old
    entry = {name: capture(destination(name)) for name in MAPPING}
    # Allow a retry of a verified whole bundle, but reject unknown/mixed installs.
    if entry != old and entry != new:
        raise ValueError('installed clients are not a complete known bundle')
    gateway = runtime.guard(release)
    comfy = runtime.identity('comfyui.service')
    hermes = runtime.identity('hermes-gateway.service', True)
    touched = False

    def guard():
        if runtime.guard(release) != gateway or runtime.identity('comfyui.service') != comfy:
            raise ValueError('Gateway or ComfyUI changed during transition')

    try:
        for name, saved in desired.items():
            guard()
            touched = True  # replace may succeed before a subsequent fsync fails
            install(destination(name), saved)
        guard()
        new_hermes = runtime.restart(hermes)
        guard()
        if {n: capture(destination(n)) for n in MAPPING} != desired:
            raise ValueError('installed bundle verification failed')
        if runtime.identity('hermes-gateway.service', True) != new_hermes:
            raise ValueError('Hermes restarted unexpectedly')
        return new_hermes
    except BaseException:
        if touched:
            try:
                guard()
                for name, saved in entry.items():
                    guard()
                    install(destination(name), saved)
                # Always reload the restored helper, even after a partial write.
                recovered = runtime.restart(hermes)
                guard()
                if ({n: capture(destination(n)) for n in MAPPING} != entry
                        or runtime.identity('hermes-gateway.service', True) != recovered):
                    raise ValueError('entry bundle recovery verification failed')
                print('RECOVERY: entry client bundle restored; transition remains FAILED')
            except BaseException:
                print('RECOVERY FAILED: retain D.6 release and recovery evidence; executor intervention required')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'restore'])
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True,
                        help='original TSV manifest inside immutable snapshot')
    parser.add_argument('--hermes-user', required=True, help='existing Hermes user service owner')
    parser.add_argument('--quiesced', action='store_true', required=True,
                        help='executor confirms ingress and analysis remain quiesced for the window')
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError('controlled privileged executor required')
        # Serialize bundle executors; ingress remains an operator-owned gate.
        lock = open('/run/lock/ai-platform-d6-clients.lock', 'a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = args.release.resolve(strict=True)
        old = backup_bundle(SNAPSHOT, args.manifest)
        new = candidate_bundle(release)
        runtime = Runtime(args.hermes_user)
        def interrupted(signum, frame):
            raise InterruptedError('transition interrupted')
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, interrupted)
        baseline = transition(args.action, release, old, new, runtime)
    except BaseException:
        raise SystemExit('FAIL: D.6 client bundle transition; do not switch releases or resume validation') from None
    print(f'PASS: {args.action} client bundle; new Hermes PID baseline={baseline[0]}; ComfyUI unchanged; Gateway idle')


if __name__ == '__main__':
    main()
