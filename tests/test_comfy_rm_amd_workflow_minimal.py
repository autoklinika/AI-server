"""Minimal AMD ComfyUI workflow regression; CPU only, no server actions."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = ROOT / "tools/local_image/generate_image.py"
EDIT = ROOT / "tools/local_image/generate_image_edit.py"


def _source_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _text_workflow() -> dict:
    # Evaluate only the static workflow dictionary assignment, never the
    # generator module (its top-level guard requires a live RM ticket).
    tree = _source_ast(TEXT)
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "workflow"
                for target in node.targets)
    )
    scope = {"prompt": "DEV", "width": 256, "height": 256, "seed": 17}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]),
                 str(TEXT), "exec"), scope)
    return scope["workflow"]


def _edit_workflow() -> dict:
    tree = _source_ast(EDIT)
    func = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "build_workflow")
    scope = {}
    exec(compile(ast.Module(body=[func], type_ignores=[]),
                 str(EDIT), "exec"), scope)
    return scope["build_workflow"]("DEV_INPUT.png", "DEV", 17)


def _assert_cpu_clip_amd_flux(workflow: dict) -> None:
    types = {node["class_type"] for node in workflow.values()}
    assert {"UNETLoader", "CLIPLoader", "VAELoader", "SaveImage",
            "SamplerCustomAdvanced"} <= types
    clip = next(node["inputs"] for node in workflow.values()
                if node["class_type"] == "CLIPLoader")
    assert clip == {"clip_name": "qwen_3_4b.safetensors",
                    "type": "flux2", "device": "cpu"}
    unet = next(node["inputs"] for node in workflow.values()
                if node["class_type"] == "UNETLoader")
    assert unet["unet_name"] == "flux-2-klein-4b-fp8.safetensors"
    vae = next(node["inputs"] for node in workflow.values()
               if node["class_type"] == "VAELoader")
    assert vae["vae_name"] == "flux2-vae.safetensors"


def test_text_to_image_cpu_encoder_and_amd_diffusion():
    workflow = _text_workflow()
    _assert_cpu_clip_amd_flux(workflow)
    latent = next(node["inputs"] for node in workflow.values()
                  if node["class_type"] == "EmptyFlux2LatentImage")
    assert (latent["width"], latent["height"]) == (256, 256)


def test_image_edit_cpu_encoder_and_amd_diffusion():
    workflow = _edit_workflow()
    _assert_cpu_clip_amd_flux(workflow)
    assert "LoadImage" in {node["class_type"] for node in workflow.values()}


def test_keep_existing_rm_admission_not_direct_gpu_bypass():
    text = TEXT.read_text()
    edit = EDIT.read_text()
    assert 'require_external_media_use("image-generation")' in text
    assert 'require_external_media_use("image-edit")' in edit
    assert 'COMFY = "http://127.0.0.1:8188"' in text
    assert 'COMFY = "http://127.0.0.1:8188"' in edit
    # No new local scheduler, backend instance or systemd process.
    for content in (text, edit):
        assert "PriorityScheduler(" not in content
        assert "systemd-run" not in content
        assert "systemctl start" not in content
