"""No host/GPU use: CPU-only tests of explicit, read-only audit facts."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('vision_preflight',
    Path(__file__).resolve().parents[1] / 'tools/vision_integration_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_empty_or_spoofed_status_cannot_prove_idle():
    for payload in ({}, {'active_count': 0}, {'gpu_reuse_safe': 'PASS'}):
        assert preflight.host_facts(payload)['gateway_idle'] is False


def test_idle_does_not_imply_gpu_reuse_or_vision_permission():
    payload = {'active_count': 0, 'queued_count': 0, 'admission_blocked': False,
               'resource_leases': {'lease_count': 0},
               'gpu_residency': {'recovery_required': False},
               'resource_manager': {'state': 'IDLE', 'engines': [
                   {'id': 'vision', 'execution_available': False}]}}
    facts = preflight.host_facts(payload)
    assert facts['gateway_idle'] is True
    assert facts['gpu_reuse_safe'] == 'UNKNOWN'
    assert facts['production_vision_execution_available'] is False
