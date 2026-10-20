"""Recover only the pinned transient-property rejection, before worker exec.

The installer injects `base` from separately verified bytes. No root imports
from the operator-writable checkout are performed here.
"""
import json
import os
from pathlib import Path
import re
import secrets

OLD_SHA = '1a527a432f3181de0a5da60bfe11bd9a4d9eb7d7e1d11667ef3038368d51ae37'
base = None


def trusted_json(path):
    info = path.stat()
    base.require(path.is_file() and not path.is_symlink() and info.st_uid == 0
                 and not info.st_mode & 0o022, 'untrusted recovery evidence')
    return json.loads(path.read_text())


def rejected_execution():
    state = base.STATE
    base.require(not (state / 'ownership.tmp').exists(), 'unfinished ownership write')
    own = trusted_json(state / 'ownership.dirty')
    base.require(set(own) == {'owner', 'unit', 'session', 'boot'}, 'unknown ownership schema')
    session = own['session']
    base.require(type(session) is dict and set(session) == {'generation', 'worker_id', 'resource_id'},
                 'unknown session schema')
    token = session['generation']
    base.require(type(token) is str and re.fullmatch('[0-9a-f]{32}', token), 'invalid session token')
    unit = 'ai-radio-' + token + '.service'
    base.require(own['unit'] == session['worker_id'] == unit
                 and session['resource_id'] == 'local-primary'
                 and own['boot'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'ownership identity/boot changed')
    owner = own['owner']
    base.require(type(owner) is dict and set(owner) == {'lease_id', 'use_id', 'job_id'}
                 and type(owner['job_id']) is int and 0 < owner['job_id'] < 2**63
                 and all(type(owner[k]) is str and re.fullmatch('[A-Za-z0-9_-]{16,64}', owner[k])
                         for k in ('lease_id', 'use_id')), 'invalid owner evidence')
    sessions = state / 'sessions'
    folder = sessions / token
    data = folder / 'data'
    for path, uid in ((sessions, 0), (folder, 0), (data, 994)):
        info = path.stat()
        base.require(path.is_dir() and not path.is_symlink() and info.st_uid == uid
                     and not info.st_mode & 0o022, 'unexpected session permissions')
    base.require(set(sessions.iterdir()) == {folder} and set(folder.iterdir()) == {data}
                 and not any(data.iterdir()), 'worker/control artifacts exist; recovery refused')
    error = trusted_json(state / 'LAST_ERROR.json')
    base.require(error == {'type': 'RuntimeError', 'reason': 'system command failed: systemd-run'},
                 'not the pinned systemd launch rejection')
    base.require(not base.command('systemctl', 'list-units', '--all', '--no-legend', '--plain', 'ai-radio-*'),
                 'RADIO unit exists')
    status = dict(line.split('=', 1) for line in base.command('systemctl', 'show', unit,
                  '-p', 'LoadState', '-p', 'MainPID', '-p', 'InvocationID').splitlines())
    base.require(status == {'LoadState': 'not-found', 'MainPID': '0', 'InvocationID': ''},
                 'unit was registered or process evidence exists')
    base.require(not Path('/sys/fs/cgroup/system.slice/' + unit).exists(), 'worker cgroup remains')
    base.require(not base.command('journalctl', '--boot', '-u', unit, '--no-pager', '-o', 'json'),
                 'worker unit journal exists; cannot prove rejected launch')
    # OS session processes may share UID 994. Worker identity is the owned
    # systemd invocation above; host_evidence() independently rejects every
    # foreign GPU FD/KFD owner before any block can be archived.
    return own


def preflight():
    base.require(os.geteuid() == 0, 'operator authorization required')
    previous = base.previous_installation(OLD_SHA)
    report = trusted_json(base.STATE / 'PILOT_RESULT.json')
    base.require(report.get('result') == 'BLOCKED' and report.get('prior_gateway_restored') is True
                 and report.get('error') == 'RuntimeError: Gateway child failed: RuntimeError: Vision prepare failed closed'
                 and report.get('supervisor_error') == {'type': 'RuntimeError', 'reason': 'system command failed: systemd-run'}
                 and report.get('production_install') == 'NOT_PERFORMED' and not report.get('radio_inspections'),
                 'report does not match pinned launch failure')
    own = rejected_execution()
    evidence = base.host_evidence(report)
    return {'previous_unit': previous, 'report': report, 'ownership': own, 'evidence': evidence,
            'old_manifest_sha256': OLD_SHA, 'reason': 'SYSTEMD_TRANSIENT_PROPERTY_REJECTED_BEFORE_WORKER_EXEC'}


def archive_ownership(proof):
    # The global block remains throughout package installation. Preserve the
    # exact rejected attempt, never erase an unknown ownership marker.
    base.previous_installation(OLD_SHA)
    base.require(rejected_execution() == proof['ownership'], 'ownership changed since preflight')
    base.host_evidence(proof['report'])
    archive = base.STATE / 'launch-rejection-recovery' / secrets.token_hex(12)
    archive.mkdir(parents=True, mode=0o700)
    (archive / 'PROOF.json').write_text(json.dumps(proof, sort_keys=True, indent=2) + '\n')
    with (archive / 'PROOF.json').open('rb') as stream:
        os.fsync(stream.fileno())
    base.sync_dir(archive)
    for name in ('ownership.dirty', 'LAST_ERROR.json'):
        os.rename(base.STATE / name, archive / name)
    token = proof['ownership']['session']['generation']
    os.rename(base.STATE / 'sessions' / token, archive / token)
    for folder in (archive, archive.parent, base.STATE, base.STATE / 'sessions'):
        base.sync_dir(folder)
    proof['ownership_archive'] = str(archive)


def archive_and_restore(proof):
    result = base.archive_and_restore(proof)
    result['launch_rejection_recovery'] = result.pop('prelaunch_recovery')
    return result
