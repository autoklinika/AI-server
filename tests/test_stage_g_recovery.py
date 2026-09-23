import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    spec = importlib.util.spec_from_file_location('recovery_test', ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('same_boot', [True, False])
def test_recovery_never_mutates_on_same_boot_fault_or_unclear_kernel(tmp_path, same_boot):
    module = load('deploy/stage-g/cold_recovery.py')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    (tmp_path / 'gpu-blocked.json').write_text(json.dumps({'boot_id': boot if same_boot else 'older-boot'}))
    calls = []
    def require(value):
        if not value:
            raise RuntimeError('refused')
    def bad_kernel():
        raise RuntimeError('kernel fault')
    e = SimpleNamespace(read=lambda p: json.loads(p.read_text()), CURRENT=tmp_path)
    g = SimpleNamespace(e=e, f=SimpleNamespace(require_kernel_clear=bad_kernel), STATE=tmp_path,
                        run=lambda *args: calls.append(args), require=require, BASE=tmp_path,
                        BASE_SHA='verified', verify=lambda p: {'source_git_sha': 'verified'})
    with pytest.raises(RuntimeError):
        module.recover_if_needed(g)
    assert calls == []


def test_kernel_guard_latches_and_contains_during_settling(tmp_path):
    module = load('deploy/stage-f/gpu_watch.py')
    count = 0
    contained = []
    def run(args):
        nonlocal count
        count += 1
        return ('amdgpu: MES ring buffer is full.\n' if count > 1 else '') + '-- cursor: test\n'
    guard = module.KernelGuard(run, lambda: contained.append(True), tmp_path / 'fault.log')
    with pytest.raises(RuntimeError, match='blocked'):
        with guard:
            assert guard.blocked.wait(3)
            guard.check()
    assert contained == [True]
    assert 'MES ring buffer is full' in (tmp_path / 'fault.log').read_text()
    assert not (tmp_path / 'fault.verified').exists()
