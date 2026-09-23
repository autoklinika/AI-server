"""Content-free reference audit: runtime blockers vs retained recovery references."""
import os
import json
import hashlib
import re
from pathlib import Path
import subprocess


def files(root):
    if not root.exists():
        return
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if d not in ('.git', '.venv', 'venv', '__pycache__', 'node_modules')]
        for name in names:
            p = Path(current) / name
            if p.is_file() and not p.is_symlink():
                yield p


def references(path, needles):
    # Never publish file contents: configuration can contain credentials.
    with path.open('rb') as stream:
        data = stream.read(4096)
        if b'\0' in data:
            return []
        data += stream.read()
    # Also detect Python imports without '.py', without mistaking the retained
    # generate_ltx23_stage30 module for the retired generate_ltx23 module.
    return [needle for needle in needles if re.search(
        rb'(?<![A-Za-z0-9_])' + re.escape(needle.removesuffix('.py').encode()) +
        rb'(?:\.py)?(?![A-Za-z0-9_])', data)]


def collect(g, q):
    e, run, require = g.e, g.run, g.require
    paths = [str(q.INSTALLED / name) for name in q.NAMES]
    release = e.CURRENT.resolve()
    # Reproduce the supported generator's script import path without inference.
    # Matching basenames inside immutable releases are retained local modules,
    # not permission to remove a still-imported installed libexec copy.
    script = release / 'services/ai-bridge/tools/local_video/generate_ltx23_stage30.py'
    probe = """
import json, runpy, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent))
ns = runpy.run_path(sys.argv[1])
print(json.dumps([str(Path(m.__file__).resolve()) for m in (ns['stage29'], ns['stage29'].base)]))
"""
    name, uid, home = e.hermes_account()
    origins = json.loads(run(['runuser', '-u', name, '--', 'env', f'HOME={home}',
        'PYTHONDONTWRITEBYTECODE=1', release / 'services/ai-bridge/.venv/bin/python',
        '-c', probe, script]))
    require(len(origins) == 2 and all(Path(p).is_relative_to(release) for p in origins))
    blockers, installed_refs, process_refs, unit_refs = [], [], [], []
    # Installed import/command names are relevant; references between the four
    # retired files form the quarantined closed group, never an active caller.
    for root in (Path('/usr/local/bin'), q.INSTALLED):
        for p in files(root):
            if p.parent == q.INSTALLED and p.name in q.NAMES:
                continue
            hits = references(p, q.NAMES)
            if hits:
                installed_refs.append({'file': str(p), 'targets': hits})
    blockers.extend(installed_refs)
    for root in (Path('/etc/systemd/system'), Path('/usr/lib/systemd/system'),
                 Path('/home/harrypotter/.config/systemd/user'), Path('/etc/ai-gateway'),
                 Path('/etc/ai-bridge')):
        for p in files(root):
            hits = references(p, q.NAMES)
            if hits:
                unit_refs.append({'file': str(p), 'targets': hits})
    for p in (Path('/srv/ai-data/hermes/config.yaml'), Path('/srv/ai-data/hermes/.env')):
        if p.is_file():
            hits = references(p, q.NAMES)
            if hits:
                unit_refs.append({'file': str(p), 'targets': hits})
    blockers.extend(unit_refs)
    effective_units = []
    for unit in ('ai-gateway.service', 'ai-bridge.service', 'ai-bridge-analysis.service', 'hermes-gateway.service'):
        args = ['show', unit, '-p', 'ExecStart', '-p', 'Environment', '-p', 'EnvironmentFiles', '-p', 'WorkingDirectory']
        value = e.user_systemctl(args) if unit == 'hermes-gateway.service' else run(['systemctl', *args])
        hits = [p for p in paths if p in value]
        env_files = []
        for line in value.splitlines():
            if not line.startswith('EnvironmentFiles='):
                continue
            for filename, optional in re.findall(r'(\S+) \(ignore_errors=(yes|no)\)', line.removeprefix('EnvironmentFiles=')):
                p = Path(filename)
                if not p.exists() and optional == 'yes':
                    continue
                found = references(p, q.NAMES)
                env_files.append({'file': filename, 'targets': found})
                hits.extend(found)
        effective_units.append({'unit': unit, 'sha256': hashlib.sha256(value.encode()).hexdigest(),
                                'environment_files': env_files, 'targets': hits})
        if hits:
            blockers.append({'unit': unit, 'targets': hits})
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            data = (proc / 'cmdline').read_bytes() + (proc / 'environ').read_bytes()
            matches = [p for p in paths if p.encode() in data]
            for link in [proc / 'cwd', proc / 'exe', *list((proc / 'fd').iterdir())]:
                try:
                    resolved = os.readlink(link)
                except FileNotFoundError:
                    continue
                if resolved in paths:
                    matches.append(resolved)
            if matches:
                process_refs.append({'pid': int(proc.name), 'targets': sorted(set(matches))})
        except (FileNotFoundError, ProcessLookupError):
            continue
    blockers.extend(process_refs)
    # Worktrees stay registered and in place. Record reference files/dirty state,
    # not diffs or source contents; historical installers remain supported recovery.
    trees = []
    for row in e.git_run(['worktree', 'list', '--porcelain']).splitlines():
        if not row.startswith('worktree '):
            continue
        root = Path(row.removeprefix('worktree '))
        require(root.is_dir() and (root / '.git').exists())
        command = ['runuser', '-u', 'harrypotter', '--', 'git', '-C', root]
        result = subprocess.run([str(x) for x in command + ['grep', '-Il', '-F',
            *[x for name in q.NAMES for x in ('-e', name)]]], capture_output=True, text=True)
        require(result.returncode in (0, 1))
        trees.append({'path': str(root), 'head': run(command + ['rev-parse', 'HEAD']),
                      'dirty_paths': len(run(command + ['status', '--porcelain']).splitlines()),
                      'reference_files': result.stdout.splitlines(), 'decision': 'KEEP: registered development/recovery tree'})
    releases = []
    for root in sorted(Path('/opt/ai-platform/releases').iterdir()):
        require(root.is_dir() and not root.is_symlink())
        matches = []
        for p in files(root / 'metadata'):
            hits = references(p, q.NAMES)
            if hits:
                matches.append({'file': str(p), 'targets': hits})
        releases.append({'path': str(root), 'metadata_references': matches,
                         'decision': 'KEEP: release/recovery/incident evidence'})
    recovery = []
    for root in (Path('/srv/ai-data/platform/recovery'), g.ROOT / 'deploy', g.ROOT / 'tools'):
        for p in files(root):
            if p.suffix not in ('.py', '.sh', '.md', '.tsv', '.json', '.yaml'):
                continue
            hits = references(p, q.NAMES)
            if hits:
                recovery.append({'file': str(p), 'targets': hits,
                    'handling': 'RETAIN; restore H manifest before historical installer/rollback use'})
    report = {'installed_callers': installed_refs, 'systemd_config_callers': unit_refs,
              'runtime_callers': process_refs, 'blockers': blockers, 'worktrees': trees,
              'current_release': str(e.CURRENT.resolve()), 'releases': releases,
              'active_generator_import_origins': origins,
              'effective_systemd': effective_units,
              'recovery_references': recovery,
              'kept': ['/opt/ai-bridge', '/opt/ai-gateway', '/srv/ai-data', '/opt/comfyui',
                       'all models', 'D.0/D.6 snapshots', 'all F/G releases and incident evidence'],
              'scope': 'four unused libexec copies only; no directory/model/state deletion'}
    return report
