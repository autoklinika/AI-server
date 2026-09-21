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
        "preflight_from_info",
        lambda info, require_upscale=False, require_i2v=False: {
            "ok": True,
            "missing_nodes": [],
            "missing_models": [],
        },
    )

    out = mod.preflight_from_info({"ImageScale": {}}, require_i2v=True)
    assert out["ok"] is True
    assert out["stage"] == 30
    assert out["i2v_resize_method"] == "lanczos"

    out = mod.preflight_from_info({}, require_i2v=True)
    assert out["ok"] is False
    assert "ImageScale" in out["missing_nodes"]


def test_stage30_preflight_reads_backend_info_through_media_adapter(monkeypatch):
    monkeypatch.setattr(
        mod.stage29,
        "preflight_from_info",
        lambda info, require_upscale=False, require_i2v=False: {
            "ok": True,
            "missing_nodes": [],
            "missing_models": [],
        },
    )

    class FakeAdapter:
        def object_info(self):
            return {"ImageScale": {}}

    monkeypatch.setattr(
        mod,
        "_media_adapter",
        lambda comfy_url, comfy_input_dir: FakeAdapter(),
    )

    out = mod.preflight("http://127.0.0.1:8188", require_i2v=True)
    assert out["ok"] is True


def test_stage30_workflow_plan_preserves_graph_and_output_naming():
    request = mod.MediaGenerationRequest(
        request_id="req-stage30",
        capability="video-generation",
        profile="ltx23-stage30",
        prompt="robot takes one step",
        output_dir="/tmp/out",
        input_artifacts=("/tmp/input.png",),
        parameters={
            "width": 640,
            "height": 384,
            "frames": 97,
            "fps": 24,
            "seed": 1,
            "negative": "bad",
            "upscale_2x": True,
            "i2v_compression": 18,
            "i2v_strength": None,
            "i2v_hq_reinject_strength": 1.0,
        },
    )

    plan = mod._workflow_plan(request, ("staged.png",))
    expected = mod.build_prompt(
        "robot takes one step",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=True,
        staged_image_name="staged.png",
        i2v_compression=18,
        i2v_strength=None,
        i2v_hq_reinject_strength=1.0,
    )

    assert plan.graph == expected
    assert plan.filename_tag == "ltx23-2x"
    assert plan.media_type == "video/mp4"
    assert plan.metadata["workflow"] == "ltx23-stage30"
    assert plan.metadata["mode"] == "i2v"


def test_active_stage30_has_no_direct_comfyui_transport_calls():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for token in ('"/prompt"', '"/history/', '"/view?', '"/free"'):
        assert token not in source
    assert "stage29.base.req_json" not in source
    assert "_stage_input_image" not in source
    assert "ComfyUIAdapter" in source



def test_stage30_cli_preserves_bare_output_path_contract(monkeypatch, tmp_path, capsys):
    output = tmp_path / "ltx23-20260921-test.mp4"
    output.write_bytes(b"video")
    captured = {}

    class Artifact:
        uri = str(output)

    class Result:
        artifacts = (Artifact(),)

    class FakeAdapter:
        def generate(self, request):
            captured["request"] = request
            return Result()

    monkeypatch.setattr(
        mod,
        "_media_adapter",
        lambda comfy_url, comfy_input_dir: FakeAdapter(),
    )

    rc = mod.main(
        [
            "--prompt",
            "red robot waves",
            "--duration-seconds",
            "2",
            "--seed",
            "123",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert capsys.readouterr().out.strip() == str(output)
    request = captured["request"]
    assert request.capability == "video-generation"
    assert request.profile == "ltx23-stage30"
    assert request.prompt == "red robot waves"
    assert request.input_artifacts == ()
    assert request.parameters["frames"] == 49
    assert request.parameters["fps"] == 24
    assert request.parameters["seed"] == 123
    assert request.parameters["upscale_2x"] is False
