from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_video" / "generate_ltx23_stage30.py"
spec = importlib.util.spec_from_file_location("generate_ltx23_stage30_test", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _assert_stage29_tiled_decode(node: dict, samples: list):
    assert node["class_type"] == "VAEDecodeTiled"
    assert node["inputs"] == {
        "samples": samples,
        "vae": ["1", 2],
        "tile_size": 512,
        "overlap": 64,
        "temporal_size": 32,
        "temporal_overlap": 8,
    }


def test_t2v_graph_remains_stage29_shape():
    graph = mod.build_prompt(
        "robot waves",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=False,
    )
    assert graph["10"]["inputs"]["video_latent"] == ["7", 0]
    assert "30" not in graph
    _assert_stage29_tiled_decode(graph["17"], ["16", 0])


def test_standard_i2v_uses_lanczos_compression18_and_gentler_anchor():
    graph = mod.build_prompt(
        "robot takes one step",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=False,
        staged_image_name="stage30_i2v_test.png",
    )
    assert graph["30"] == {
        "class_type": "LoadImage",
        "inputs": {"image": "stage30_i2v_test.png"},
    }
    assert graph["31"] == {
        "class_type": "ImageScale",
        "inputs": {
            "image": ["30", 0],
            "upscale_method": "lanczos",
            "width": 640,
            "height": 384,
            "crop": "center",
        },
    }
    assert graph["32"]["class_type"] == "LTXVPreprocess"
    assert graph["32"]["inputs"]["img_compression"] == 18
    assert graph["33"]["class_type"] == "LTXVImgToVideoInplace"
    assert graph["33"]["inputs"]["image"] == ["32", 0]
    assert graph["33"]["inputs"]["latent"] == ["7", 0]
    assert graph["33"]["inputs"]["strength"] == 0.85
    assert graph["33"]["inputs"]["bypass"] is False
    assert graph["10"]["inputs"]["video_latent"] == ["33", 0]
    _assert_stage29_tiled_decode(graph["17"], ["16", 0])


def test_hq_i2v_uses_official_like_070_then_100_anchors():
    graph = mod.build_prompt(
        "robot takes one step",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=True,
        staged_image_name="stage30_i2v_test.png",
    )
    assert graph["33"]["inputs"]["strength"] == 0.70
    assert graph["34"]["class_type"] == "ImageScale"
    assert graph["34"]["inputs"]["width"] == 1280
    assert graph["34"]["inputs"]["height"] == 768
    assert graph["34"]["inputs"]["upscale_method"] == "lanczos"
    assert graph["35"]["class_type"] == "LTXVPreprocess"
    assert graph["35"]["inputs"]["img_compression"] == 18
    assert graph["36"]["class_type"] == "LTXVImgToVideoInplace"
    assert graph["36"]["inputs"]["image"] == ["35", 0]
    assert graph["36"]["inputs"]["latent"] == ["18", 0]
    assert graph["36"]["inputs"]["strength"] == 1.0
    assert graph["36"]["inputs"]["bypass"] is False
    assert graph["19"]["inputs"]["video_latent"] == ["36", 0]
    _assert_stage29_tiled_decode(graph["26"], ["25", 0])


def test_ab_overrides_are_explicit_and_bounded():
    graph = mod.build_prompt(
        "robot moves",
        width=640,
        height=384,
        frames=49,
        fps=24,
        seed=1,
        negative="bad",
        staged_image_name="x.png",
        i2v_compression=25,
        i2v_strength=1.0,
    )
    assert graph["32"]["inputs"]["img_compression"] == 25
    assert graph["33"]["inputs"]["strength"] == 1.0

    for bad in (-0.01, 1.01):
        try:
            mod.build_prompt(
                "robot moves",
                width=640,
                height=384,
                frames=49,
                fps=24,
                seed=1,
                negative="bad",
                staged_image_name="x.png",
                i2v_strength=bad,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid I2V strength must fail")


def test_preflight_requires_core_image_scale_for_stage30_i2v(monkeypatch):
    monkeypatch.setattr(
        mod.stage29,
        "preflight",
        lambda url, require_upscale=False, require_i2v=False: {
            "ok": True,
            "missing_nodes": [],
            "missing_models": [],
        },
    )
    monkeypatch.setattr(
        mod.stage29.base,
        "req_json",
        lambda *args, **kwargs: {"ImageScale": {}},
    )
    out = mod.preflight("http://127.0.0.1:8188", require_i2v=True)
    assert out["ok"] is True
    assert out["stage"] == 30
    assert out["i2v_resize_method"] == "lanczos"

    monkeypatch.setattr(
        mod.stage29.base,
        "req_json",
        lambda *args, **kwargs: {},
    )
    out = mod.preflight("http://127.0.0.1:8188", require_i2v=True)
    assert out["ok"] is False
    assert "ImageScale" in out["missing_nodes"]
