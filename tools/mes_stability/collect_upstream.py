#!/usr/bin/env python3
"""Download pinned upstream evidence; never execute it or install packages."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

URLS = {
    'tlb.patch': 'https://github.com/torvalds/linux/commit/e9f58ff991dd4be13fd7a651bbf64329c090af09.patch',
    'v7-amdgpu_vm.c': 'https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.c',
    'v7-mes_v11_0.c': 'https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/gpu/drm/amd/amdgpu/mes_v11_0.c',
    'v7-gmc_v11_0.c': 'https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/gpu/drm/amd/amdgpu/gmc_v11_0.c',
    'rocr-openclose.c': 'https://raw.githubusercontent.com/ROCm/ROCR-Runtime/rocm-7.2.1/libhsakmt/src/openclose.c',
    'rocr-fmm.c': 'https://raw.githubusercontent.com/ROCm/ROCR-Runtime/rocm-7.2.1/libhsakmt/src/fmm.c',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    evidence = {}
    for name, url in URLS.items():
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = response.read(2*1024*1024 + 1)
            if len(data) > 2*1024*1024:
                raise ValueError('unexpected large source response')
            (a.output/name).write_bytes(data)
            evidence[name] = {'url':url, 'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data)}
        except Exception as error:
            evidence[name] = {'url':url, 'error':str(error)}
    blobs = {}
    for f in Path('/lib/firmware/amdgpu').glob('gc_11_5_0_mes*.zst'):
        blobs[f.name] = {'on_disk_compressed_sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
        result = subprocess.run(['zstd','-dc',str(f)], capture_output=True, timeout=5)
        if result.returncode == 0:
            blobs[f.name]['on_disk_uncompressed_sha256'] = hashlib.sha256(result.stdout).hexdigest()
    evidence['firmware_on_disk_not_running_version'] = blobs
    (a.output/'manifest.json').write_text(json.dumps(evidence, indent=2)+'\n')
    return 1 if any('error' in v for v in evidence.values()) else 0

if __name__ == '__main__':
    raise SystemExit(main())
