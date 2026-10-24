"""CPU-only verification of strict staging-only Hermes /foto source transforms."""
import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/local_image/prepare_comfy_fullchain_isolated_dev.py"
spec = importlib.util.spec_from_file_location("comfy_fullchain_isolated_dev", SOURCE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_snapshot_transforms_only_staging_ports_and_output():
    for rel in module.SOURCE_FILES:
        original = (ROOT / rel).read_text()
        staged = module.transform(rel, original)
        ast.parse(staged, filename=rel)
        if rel in module.PORT_GATEWAY_FILES:
            assert "11435" not in staged
            assert "11656" in staged
            assert original != staged
        if rel in module.GENERATORS:
            assert "127.0.0.1:8188" not in staged
            assert 'COMFY = "http://127.0.0.1:11657"' in staged
            assert str(module.TARGET / "output") in staged
            assert "/srv/ai-data/comfyui-output" not in staged
            assert original != staged
        if rel == "tools/local_image/generate_image.py":
            assert 'default=256' in staged
            assert 'default=1024' not in staged
        if rel == "tools/local_image/generate_image_edit.py":
            assert str(module.TARGET / "input") in staged
        if rel not in module.PORT_GATEWAY_FILES + module.GENERATORS:
            assert original == staged


def test_snapshot_source_drift_refuses_unknown_generator():
    source = (ROOT / "tools/local_image/generate_image.py").read_text()
    with pytest.raises(RuntimeError, match="unexpectedly changed"):
        module.transform(
            "tools/local_image/generate_image.py",
            source.replace('COMFY = "http://127.0.0.1:8188"',
                           'COMFY = "http://127.0.0.1:8189"'),
        )


def test_snapshot_rejects_missing_gateway_reference():
    source = (ROOT / "tools/hermes_resource_queue.py").read_text()
    with pytest.raises(RuntimeError, match="reference absent"):
        module.transform("tools/hermes_resource_queue.py",
                         source.replace("11435", "11436"))


def test_original_sources_remain_production_pinned():
    for rel in module.PORT_GATEWAY_FILES:
        assert "11435" in (ROOT / rel).read_text()
    for rel in module.GENERATORS:
        assert "127.0.0.1:8188" in (ROOT / rel).read_text()


def test_staging_root_and_flags_are_fixed():
    assert str(module.TARGET) == "/srv/ai-data/staging/comfy-fullchain-dev-20261024"
    assert "generator" not in module.SOURCE_FILES
