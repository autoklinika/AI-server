"""Pure CPU-only tests: no service actions or GPU process operations."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "tools/local_image"
          / "fullchain_rollback_gate_dev.py")
spec = importlib.util.spec_from_file_location("fullchain_rollback_predicates", SOURCE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


@pytest.fixture
def clear_facts():
    return module.RestoreObservation(
        dev_unit_inactive=True,
        dev_mainpid_zero=True,
        dev_cgroup_empty=True,
        worker_identity_gone=True,
        gateway_dev_port_closed=True,
        comfy_dev_port_closed=True,
        ollama_models=(),
        amd_device_owners=(),
    )


def test_only_verified_empty_descriptors_and_processes_qualify(clear_facts):
    result = module.classify_restore_gate(clear_facts)
    assert result["restore_prerequisites"] == "PASS"
    assert result["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert result["driver_esafe"] == "NOT_VERIFIED"
    assert result["permission_to_start_production_comfy"] is False


@pytest.mark.parametrize("field,value", [
    ("dev_unit_inactive", False),
    ("dev_mainpid_zero", False),
    ("dev_cgroup_empty", False),
    ("worker_identity_gone", None),
    ("worker_identity_gone", False),
    ("gateway_dev_port_closed", False),
    ("comfy_dev_port_closed", False),
    ("amd_device_owners", None),
    ("amd_device_owners", (11111,)),
    ("ollama_models", None),
])
def test_broken_or_missing_evidence_prevents_restore(clear_facts, field, value):
    result = module.classify_restore_gate(replace(clear_facts, **{field: value}))
    assert result["restore_prerequisites"] == "BLOCKED"
    assert result["permission_to_start_production_comfy"] is False


@pytest.mark.parametrize("resident,reason", [
    ((module.QWEN,), "QWEN_STILL_RESIDENT_REQUIRES_CONTROLLED_UNLOAD"),
    (("qwen3.8:27b-p4-64k-gpu-wvc-v1",), "UNEXPECTED_OLLAMA_MODEL"),
    ((module.QWEN, "clef:latest"), "UNEXPECTED_OLLAMA_MODEL"),
])
def test_qwen_must_be_unloaded_and_foreign_models_are_not_drained(
    clear_facts, resident, reason
):
    result = module.classify_restore_gate(
        replace(clear_facts, ollama_models=resident))
    assert result["restore_prerequisites"] == "BLOCKED"
    assert reason in result["reasons"]


@pytest.mark.parametrize("payload", [
    None, {}, {"models": None}, {"models": {}},
    {"models": [None]}, {"models": [{"name": ""}]},
    {"models": [{"name": 34}]},
    {"models": [{"name": module.QWEN}, {"name": module.QWEN}]},
])
def test_untrustworthy_ollama_inventory_fails_closed(payload):
    with pytest.raises(ValueError):
        module.require_valid_ollama_inventory(payload)


def test_strict_known_model_inventory():
    assert module.require_valid_ollama_inventory({"models": []}) == ()
    assert module.require_valid_ollama_inventory(
        {"models": [{"name": module.QWEN}]}) == (module.QWEN,)
