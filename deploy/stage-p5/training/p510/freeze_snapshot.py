#!/usr/bin/env python3
"""Rebind fixed local artifacts for a BLOCKED snapshot; never certifies evidence."""
import hashlib
import json
import subprocess
from pathlib import Path
import preflight


def main():
    root = Path(__file__).resolve().parents[4]
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=root, text=True).strip()
    if branch != 'stage-p5.10/eval-foundation-v1':
        raise SystemExit('refusing snapshot write outside authorized branch')
    bindings = {}
    for name, relative in preflight.ARTIFACTS.items():
        payload = preflight.read_fixed(root, relative)
        bindings[name] = dict(path=relative, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    manifest = dict(schema_version=1, status=preflight.STATUS, acceptance_authorized=False,
                    parent=None, independent_eval=None, candidate_status='NOT_RUN',
                    blocker=preflight.BLOCKER, artifacts=bindings)
    # Validate evidence before replacing its integrity manifest. No paths from metadata are opened.
    preflight.protocol_v2.inspect(preflight.protocol_v2.load_bundle())
    target = root / preflight.PREFIX / 'artifact_manifest.json'
    if target.is_symlink():
        raise SystemExit('refusing redirected manifest')
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    result = preflight.validate(root)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
