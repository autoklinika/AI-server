"""Allowlisted, reversible legacy-helper quarantine. No purge operation exists."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat

NAMES = ('generate_ltx23.py', 'generate_ltx23_base.py', 'generate_ltx23_stage29.py',
         'hermes_video_dispatch_stage26.py')
INSTALLED = Path('/usr/local/libexec/ai-server')
QUARANTINE = Path('/usr/local/libexec/ai-server-quarantine')


def rename_exclusive(source, target):
    # Linux RENAME_NOREPLACE closes the existence-check/rename race. Refuse
    # unsupported filesystems instead of falling back to overwriting rename.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def fingerprint(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError('quarantine requires a regular, unlinked file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NOATIME', 0))
    with os.fdopen(fd, 'rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': digest, 'size': info.st_size, 'mode': stat.S_IMODE(info.st_mode),
            'uid': info.st_uid, 'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns,
            'atime_ns': info.st_atime_ns, 'device': info.st_dev, 'inode': info.st_ino,
            'xattrs': {k: base64.b64encode(os.getxattr(path, k)).decode()
                       for k in os.listxattr(path)}}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def plan(release_id, *, installed=INSTALLED, quarantine=QUARANTINE):
    if not release_id.startswith('stage-h-') or '/' in release_id or '..' in release_id:
        raise ValueError('invalid quarantine identity')
    if installed.is_symlink() or quarantine.is_symlink():
        raise RuntimeError('symlinked quarantine root')
    entries = []
    for name in NAMES:
        source, target = installed / name, quarantine / release_id / name
        if target.exists() or target.is_symlink():
            raise RuntimeError('quarantine destination already exists')
        entries.append({'source': str(source), 'target': str(target), 'fingerprint': fingerprint(source)})
    return {'schema_version': 1, 'release_id': release_id, 'entries': entries,
            'purge': 'PROHIBITED; later retention review only'}


def validate_manifest(manifest, *, installed=INSTALLED, quarantine=QUARANTINE):
    rid = manifest['release_id']
    if (manifest.get('schema_version') != 1 or not rid.startswith('stage-h-')
            or '/' in rid or '..' in rid or len(manifest['entries']) != len(NAMES)):
        raise RuntimeError('invalid quarantine manifest')
    if installed.is_symlink() or quarantine.is_symlink() or (quarantine / rid).is_symlink():
        raise RuntimeError('symlinked quarantine root')
    for name, entry in zip(NAMES, manifest['entries']):
        if entry['source'] != str(installed / name) or entry['target'] != str(quarantine / rid / name):
            raise RuntimeError('manifest path outside allowlist')


def relocate(manifest, *, restore=False, installed=INSTALLED, quarantine=QUARANTINE):
    validate_manifest(manifest, installed=installed, quarantine=quarantine)
    # Prevalidate the whole batch. Mixed source/target locations are allowed only
    # for resuming a partially completed transaction; both/neither is an error.
    pending = []
    for entry in manifest['entries']:
        source, target = Path(entry['source']), Path(entry['target'])
        if restore:
            source, target = target, source
        source_present = source.exists() or source.is_symlink()
        target_present = target.exists() or target.is_symlink()
        if source_present == target_present:
            raise RuntimeError('ambiguous quarantine ownership')
        current = source if source_present else target
        if fingerprint(current) != entry['fingerprint']:
            raise RuntimeError('quarantine content or metadata drift')
        if source_present:
            pending.append((source, target, entry['fingerprint']))
    for source, target, expected in pending:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.parent.stat().st_dev != source.stat().st_dev:
            raise RuntimeError('quarantine must use same-filesystem rename')
        if target.exists() or target.is_symlink() or fingerprint(source) != expected:
            raise RuntimeError('quarantine changed after validation')
        rename_exclusive(source, target)
        sync_directory(source.parent)
        sync_directory(target.parent)
        if fingerprint(target) != expected:
            raise RuntimeError('quarantine rename verification failed')
    verify(manifest, restored=restore, installed=installed, quarantine=quarantine)


def verify(manifest, *, restored=False, installed=INSTALLED, quarantine=QUARANTINE):
    validate_manifest(manifest, installed=installed, quarantine=quarantine)
    for entry in manifest['entries']:
        present = Path(entry['source'] if restored else entry['target'])
        absent = Path(entry['target'] if restored else entry['source'])
        if absent.exists() or absent.is_symlink() or fingerprint(present) != entry['fingerprint']:
            raise RuntimeError('quarantine state not verified')
