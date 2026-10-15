#!/usr/bin/env -S python3 -I -B -S
"""DEV transaction primitive; production adapter deliberately unavailable.

Two durable exclusive creations, not a filesystem-wide atomic transaction:
accepted is the commit marker. Any partial write requires manual review.
Injected verifier is trusted executable code, never operator JSON/CLI input.
It must hold external mutation barriers through return from commit; flock alone
cannot freeze runtime. No production implementation of that contract exists.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import time
import uuid

spec = importlib.util.spec_from_file_location(
    'recovery_preflight', Path(__file__).with_name('recover_acceptance_preflight.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
h = p.h
MODEL = 'qwen3.8:27b-p4-64k-gpu-p511'
ADAPTER_SOURCE = '46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb'
ADAPTER_RUNTIME = 'bb4966fa3d8a5a71a7e21b159235cc5e00f0282ff6c50ce6c1c41eca2dbba8a7'
PHASE = 'RECOVERED_POST_REBOOT'
ATTESTATION = 'recovery-attestation.json'


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def read_artifact(fd, name):
    item = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_NONBLOCK, dir_fd=fd)
    try:
        st = os.fstat(item)
        p.trusted(st, 0o600)
        h.require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and 0 < st.st_size <= 1048576, 'FILE_TYPE_SIZE')
        raw = bytearray()
        while len(raw) <= 1048576:
            chunk = os.read(item, 65536)
            if not chunk:
                break
            raw.extend(chunk)
        h.require(len(raw) == st.st_size and h.snapshot(st) == h.snapshot(os.fstat(item)) ==
                  h.snapshot(os.stat(name, dir_fd=fd, follow_symlinks=False)), 'TOCTOU')
        value = json.loads(raw, object_pairs_hook=h.unique_object,
                           parse_constant=lambda _: h.require(False, 'JSON_CONSTANT'))
        return value, hashlib.sha256(raw).hexdigest(), h.snapshot(st)
    finally:
        os.close(item)


def collect(fd, now):
    """Read-only collection and pure structural validation; no runtime authority."""
    p.trusted(os.fstat(fd), 0o700)
    h.require(set(os.listdir(fd)) == {n + '.json' for n in h.NAMES}, 'PARTIAL_OR_EXISTING_STATE')
    records = {n: read_artifact(fd, n + '.json') for n in h.NAMES}
    h.validate_structure({n: r[0] for n, r in records.items()}, now)
    mtimes = [r[2][-2] for r in records.values()]
    h.require(mtimes == sorted(mtimes) and max(mtimes) <= now * 10**9, 'ARTIFACT_TIME')
    return records


def validate_observation(o, records, now):
    """Pure consistency checks on trusted verifier output, NOT authentication."""
    h.require(o['source_sha'] == h.SOURCE, 'SOURCE')
    h.require(o['manifest_sha256'] == records['installed'][0]['checksums'], 'MANIFEST')
    h.require(o['clients'] == records['baseline'][0]['clients'], 'CLIENTS')
    h.require(o['model'] == MODEL and o['adapter_source'] == ADAPTER_SOURCE and
              o['adapter_runtime'] == ADAPTER_RUNTIME, 'MODEL')
    h.require(set(o['health']) == {'gateway', 'bridge', 'control_center', 'comfyui', 'ollama', 'hermes', 'analysis_timer'} and
              all(v == 'ok' for v in o['health'].values()), 'HEALTH')
    h.require(o['queue'] == 0 and o['leases'] == 0, 'QUIESCENCE')
    for name, age in [('monitor', 300), ('daily', 36 * 3600), ('weekly', 192 * 3600), ('nas', 60)]:
        entry = o[name]
        h.require(entry['status'] == 'PASS' and type(entry['time']) is int and
                  0 <= now - entry['time'] <= age and h.digest(entry['source_sha256']), 'FRESH_' + name)
    h.require(o['restore'] == 'PASS', 'RESTORE')
    h.require(len(o['config_sha256']) == 17 and all(Path(k).name == k and k not in ('.', '..') and
              h.digest(v) for k, v in o['config_sha256'].items()), 'CONFIG')
    h.require(str(uuid.UUID(o['boot_id'])) == o['boot_id'], 'BOOT_ID')
    h.require(o['approval_id'] and o['env_exception_id'] == p.DECISION, 'APPROVAL')


def exclusive_write(fd, name, raw):
    item = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(item, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(item)
    finally:
        os.close(item)
    os.fsync(fd)


def commit(state, verifier, *, clock=time.time):
    """Injected DEV core. verifier.observe/authorize/recheck must fail by raising.

    Caller owns verifier lifecycle and external barriers. Production CLI cannot
    reach this API. No retries, rollback, unlink, mkdir or overwrite on failure.
    Existing executor.lock lives in state's parent, as in Stage O gate.
    """
    h.require(os.geteuid() == 0, 'ROOT_REQUIRED')
    state = Path(state)
    h.require(state.is_absolute() and '..' not in state.parts and state.name == h.SOURCE, 'STATE_PATH')
    parent = p.directory(str(state.parent))
    lock = fd = None
    try:
        lock = os.open('executor.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        ls = os.fstat(lock)
        p.trusted(ls, 0o600)
        h.require(stat.S_ISREG(ls.st_mode) and ls.st_nlink == 1, 'LOCK')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open(state.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NOATIME, dir_fd=parent)
        identity = h.snapshot(os.fstat(fd))
        now = int(clock())
        records = collect(fd, now)
        observation = verifier.observe()
        validate_observation(observation, records, now)
        # Separate apply approval, not merely historical env exception/ID string.
        h.require(verifier.authorize(h.SOURCE, observation, records) is True, 'NO_APPLY_APPROVAL')

        def recheck():
            h.require(h.snapshot(os.stat('executor.lock', dir_fd=parent, follow_symlinks=False)) == h.snapshot(ls), 'LOCK_CHANGED')
            st = os.stat(state.name, dir_fd=parent, follow_symlinks=False)
            h.require(h.snapshot(st)[:6] == identity[:6], 'STATE_CHANGED')
            for name, original in records.items():
                h.require(read_artifact(fd, name + '.json') == original, 'TOCTOU')
            h.require(verifier.recheck(observation) is True, 'RUNTIME_CHANGED')

        recheck()
        attestation = dict(source_sha=h.SOURCE, release_id=h.RELEASE, time=now,
            phase=PHASE, boot_id=observation['boot_id'], approval_id=observation['approval_id'],
            original_sha256={n + '.json': r[1] for n, r in records.items()},
            config_sha256=observation['config_sha256'], health=observation['health'],
            env={'status': 'approved_exception', 'decision_id': p.DECISION,
                 'files': ['ai-bridge.env', 'ai-gateway.env'], 'byte_identity': 'NOT_PROVEN'},
            historical_finalize='NOT_PASSED')
        raw = encode(attestation)
        exclusive_write(fd, ATTESTATION, raw)
        recheck()  # Failure leaves immutable partial state for manual review.
        accepted = dict(status='PASS', release_id=h.RELEASE, source_sha=h.SOURCE,
            schema=h.SCHEMA, control_center_contract_version=1,
            technical_conversation_contract_version=1, llm_model=MODEL,
            llm_adapter_source_sha256=ADAPTER_SOURCE, llm_adapter_runtime_sha256=ADAPTER_RUNTIME,
            time=now, phase=PHASE, recovery_provenance={
                'attestation': ATTESTATION, 'sha256': hashlib.sha256(raw).hexdigest()})
        exclusive_write(fd, 'accepted.json', encode(accepted))
        return accepted
    finally:
        if fd is not None:
            os.close(fd)
        if lock is not None:
            os.close(lock)
        os.close(parent)


def verify_provenance(state, evidence):
    """Additional recovered-only gate; legacy acceptance retains its meaning."""
    fd_path = p.directory(str(state))
    fd = None
    try:
        fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOATIME, dir_fd=fd_path)
        p.trusted(os.fstat(fd), 0o700)
        disk, _, _ = read_artifact(fd, 'accepted.json')
        h.require(disk == evidence, 'ACCEPTED_CHANGED')
        att, digest, _ = read_artifact(fd, ATTESTATION)
        h.require(evidence['phase'] == att['phase'] == PHASE and evidence['recovery_provenance'] ==
                  {'attestation': ATTESTATION, 'sha256': digest}, 'PROVENANCE')
        h.require(att['source_sha'] == evidence['source_sha'] == h.SOURCE and
                  att['release_id'] == evidence['release_id'] == h.RELEASE and
                  att['time'] == evidence['time'] and att['approval_id'] and
                  att['historical_finalize'] == 'NOT_PASSED' and
                  att['env']['status'] == 'approved_exception' and att['env']['decision_id'] == p.DECISION,
                  'ATTESTATION_IDENTITY')
        h.require(set(att['original_sha256']) == {n + '.json' for n in h.NAMES}, 'ORIGINAL_SET')
        for name, expected in att['original_sha256'].items():
            h.require(read_artifact(fd, name)[1] == expected, 'ORIGINAL_CHANGED')
    finally:
        if fd is not None:
            os.close(fd)
        os.close(fd_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-source', choices=[h.SOURCE], default=h.SOURCE)
    args = parser.parse_args(argv)
    print(json.dumps(dict(status='CODE_READY_IN_DEV/PROD_BLOCKED', mode='APPLY_BLOCKED' if args.apply else 'CHECK',
        source_sha=h.SOURCE, apply_available=False, active_verification='NOT_IMPLEMENTED',
        blockers={k: v for k, v in p.MISSING.items() if k != 'WRITE_CONTRACT'},
        write_blockers=['Separate apply consent absent', 'Trusted production verifier and external mutation barriers absent']), sort_keys=True))
    return 2


if __name__ == '__main__':
    sys.exit(main())
