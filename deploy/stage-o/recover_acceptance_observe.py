#!/usr/bin/env -S python3 -I -B -S
"""Ograniczona aktywna obserwacja tylko do odczytu; zawsze PROD_BLOCKED.

Kontrakty GET i tożsamości procesów: deploy/stage-e/autopilot/gate.py
(runtime, idle, comfy_idle); Control Center: Stage O control_center_smoke.
Nie importuje operacyjnego gate, nie czyta env, nie wykonuje inference.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import uuid

spec = importlib.util.spec_from_file_location('recovery_core', Path(__file__).with_name('recover_acceptance_apply.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
p, h = a.p, a.h
LIMIT = 1024 * 1024
# One pinned host/release: Bridge is LAN-bound, never served on loopback.
# An address change must fail closed pending explicit revalidation.
ENDPOINTS = {
    'gateway': ('127.0.0.1', 11435, '/health'),
    'bridge': ('192.168.1.55', 8080, '/health'),
    'control_center': ('192.168.1.55', 8080, '/control/api/v1/health'),
    'jobs': ('127.0.0.1', 11435, '/status'),
    'queue': ('127.0.0.1', 8188, '/queue'),
    'residency': ('127.0.0.1', 11434, '/api/ps'),
}
UNITS = ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service', 'ai-bridge-analysis.timer')
PROPERTIES = ('ActiveState', 'MainPID', 'InvocationID', 'WorkingDirectory', 'NeedDaemonReload')
UNCOVERED = [
    'SOURCE_RELEASE_ROLLBACK: pełne metadane/checksumy, dokładny Git i rollback accepted',
    'MODEL_CONFIG: zaufany digest modelu/LoRA, preload script, routing WVC, 17 efektywnych unitów/drop-ins',
    'HERMES: stan user service i niezależna kontrola wszystkich źródeł ingress',
    'STAGE_K: świeże monitor/daily/weekly/nested restore, NAS i marker',
    'BACKUPS: przypięte manifesty PlatformConfig/Secrets, archiwa age i metadane wyjątku env',
    'FENCE: brak egzekwowanej wyłącznej dzierżawy maintenance',
    'APPROVAL: brak osobnej zgody apply',
]


def decode(raw):
    return json.loads(raw, object_pairs_hook=h.unique_object,
                      parse_constant=lambda _: h.require(False, 'JSON_CONSTANT'))


class ReadOnly:
    """Stała lista odczytów; bez parametrów poleceń/URL pochodzących z JSON."""
    def get(self, name):
        host, port, path = ENDPOINTS[name]
        conn = http.client.HTTPConnection(host, port, timeout=2)
        try:
            conn.request('GET', path, headers={'Accept': 'application/json'})
            response = conn.getresponse()
            h.require(response.status == 200, 'HTTP_STATUS')
            raw = response.read(LIMIT + 1)
            h.require(len(raw) <= LIMIT, 'HTTP_SIZE')
            return decode(raw)
        finally:
            conn.close()

    def file(self, path):
        parent = p.directory(str(Path(path).parent))
        fd = None
        try:
            fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_NONBLOCK, dir_fd=parent)
            st = os.fstat(fd)
            p.trusted(st)
            h.require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= LIMIT, 'FILE_TYPE_SIZE')
            raw = os.read(fd, LIMIT + 1)
            h.require(len(raw) == st.st_size and h.snapshot(st) == h.snapshot(os.fstat(fd)) ==
                      h.snapshot(os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)), 'FILE_CHANGED')
            return raw, [hashlib.sha256(raw).hexdigest(), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid]
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def link(self, path):
        return os.readlink(path)

    def boot(self):
        with open('/proc/sys/kernel/random/boot_id', encoding='ascii') as stream:
            return stream.read(128).strip()

    def unit(self, name):
        h.require(name in UNITS, 'UNIT_ALLOWLIST')
        result = subprocess.run(['/usr/bin/systemctl', 'show', name,
            '--property=' + ','.join(PROPERTIES)], check=True, capture_output=True,
            timeout=2, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, text=True)
        h.require(len(result.stdout) <= 16384, 'UNIT_SIZE')
        pairs = [line.split('=', 1) for line in result.stdout.splitlines()]
        return h.unique_object(pairs)


def sample(io, baseline):
    boot = io.boot()
    h.require(str(uuid.UUID(boot)) == boot, 'BOOT_ID')
    current = io.link(p.CURRENT)
    h.require(current == p.RELEASE, 'CURRENT')
    clients = {name: io.file(name)[1] for name in sorted(h.CLIENTS)}
    h.require(clients == baseline['clients'], 'CLIENTS')
    preload = io.file('/etc/systemd/system/ollama-preload.service')[0]
    h.require(preload.decode('utf-8') == baseline['preload_unit'], 'PRELOAD_UNIT')
    units = {}
    for name in UNITS:
        unit = io.unit(name)
        h.require(set(unit) == set(PROPERTIES), 'UNIT_PROPERTIES')
        h.require(unit['ActiveState'] == 'active' and unit['NeedDaemonReload'] == 'no', 'UNIT_STATE')
        h.require(re.fullmatch('[0-9a-f]{32}', unit['InvocationID']) is not None, 'INVOCATION')
        if name.endswith('.service'):
            h.require(re.fullmatch('[1-9][0-9]*', unit['MainPID']) is not None, 'PID')
        if name in UNITS[:2]:
            service = name[:-8]
            h.require(unit['WorkingDirectory'] == p.CURRENT + '/services/' + service, 'WORKDIR')
            h.require(io.link('/proc/' + unit['MainPID'] + '/cwd') == p.RELEASE + '/services/' + service, 'PROCESS_CWD')
        units[name] = unit
    for name in ('gateway', 'bridge'):
        h.require(io.get(name)['status'] == 'ok', 'HEALTH_' + name)
    h.require(io.get('control_center')['readiness'] is True, 'HEALTH_control_center')
    jobs = io.get('jobs')
    counts = [jobs['active_count'], jobs['queued_count'], jobs['resource_leases']['lease_count']]
    h.require(all(type(n) is int and n == 0 for n in counts), 'INGRESS_BUSY')
    queue = io.get('queue')
    h.require(queue['queue_running'] == [] and queue['queue_pending'] == [], 'COMFY_BUSY')
    models = io.get('residency')['models']
    h.require(type(models) is list and len(models) == 1, 'RESIDENCY')
    model = models[0]
    h.require(model['name'] == a.MODEL and h.digest(model['digest']), 'MODEL')
    # Digest obserwowany, nie uwierzytelniony historycznie. Nie dowodzi LoRA/E_safe.
    return dict(boot=boot, current=current, clients=clients, units=units,
                model={'name': model['name'], 'digest': model['digest']},
                preload_sha256=hashlib.sha256(preload).hexdigest())


def observe(io, records):
    first = sample(io, records['baseline'][0])
    h.require(sample(io, records['baseline'][0]) == first, 'GENERATION_CHANGED')
    return first


def production_observe():
    h.require(os.geteuid() == 0, 'ROOT_REQUIRED')
    parent = p.directory(p.STATE)
    lock = fd = None
    try:
        lock = os.open('executor.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        ls = os.fstat(lock)
        p.trusted(ls, 0o600)
        h.require(stat.S_ISREG(ls.st_mode) and ls.st_nlink == 1, 'LOCK')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(h.SOURCE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NOATIME, dir_fd=parent)
        identity = h.snapshot(os.fstat(fd))
        records = a.collect(fd, int(time.time()))
        result = observe(ReadOnly(), records)
        h.require(a.collect(fd, int(time.time())) == records, 'ORIGINAL_CHANGED')
        h.require(h.snapshot(os.stat(h.SOURCE, dir_fd=parent, follow_symlinks=False)) == identity, 'STATE_CHANGED')
        h.require(h.snapshot(os.stat('executor.lock', dir_fd=parent, follow_symlinks=False)) == h.snapshot(ls), 'LOCK_CHANGED')
        return result
    finally:
        for descriptor in (fd, lock, parent):
            if descriptor is not None:
                os.close(descriptor)


def expired(*_):
    raise TimeoutError('OBSERVATION_TIMEOUT')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--observe', action='store_true', required=True)
    parser.parse_args(argv)
    report = dict(status='PROD_BLOCKED', apply_available=False, observation='REJECTED', uncovered=UNCOVERED)
    # Twardy całkowity limit obejmuje również powolne odczyty HTTP i plików.
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        result = production_observe()
        report['observation'] = 'LIMITED_READ_ONLY_CONSISTENT'
        report['observation_sha256'] = hashlib.sha256(a.encode(result)).hexdigest()
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError, http.client.HTTPException) as error:
        # Nigdy nie drukuj payloadu API, stderr polecenia ani zawartości pliku.
        code = str(error)
        report['diagnostic'] = code if type(error) in (ValueError, TimeoutError) and re.fullmatch('[A-Z_]{3,80}', code) else 'READ_OR_CONTRACT_OR_TIMEOUT_REJECTED'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2


if __name__ == '__main__':
    sys.exit(main())
