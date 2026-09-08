from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "local_video" / "generate_video.py"
spec = importlib.util.spec_from_file_location("local_video_generator", MODULE_PATH)
assert spec and spec.loader
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)


def _prompt(**overrides):
    args = dict(
        prompt="a robot waves",
        width=640,
        height=352,
        frames=49,
        steps=10,
        cfg=5.0,
        fps=24.0,
        seed=123,
        negative_prompt="bad",
    )
    args.update(overrides)
    return video.build_prompt(**args)


def test_text_to_video_graph_uses_official_wan22_nodes():
    graph = _prompt()
    assert graph["1"]["class_type"] == "UNETLoader"
    assert graph["1"]["inputs"]["unet_name"] == video.MODEL_NAME
    assert graph["2"]["inputs"]["clip_name"] == video.TEXT_ENCODER
    assert graph["3"]["inputs"]["vae_name"] == video.VAE_NAME
    assert graph["7"]["class_type"] == "Wan22ImageToVideoLatent"
    assert "start_image" not in graph["7"]["inputs"]
    assert graph["8"]["inputs"]["sampler_name"] == "uni_pc"
    assert graph["10"]["class_type"] == "CreateVideo"
    assert graph["10"]["inputs"]["fps"] == 24.0
    assert graph["11"]["class_type"] == "SaveVideo"
    assert graph["11"]["inputs"]["format"] == "mp4"
    assert graph["11"]["inputs"]["codec"] == "h264"


def test_image_to_video_adds_load_image_and_start_image_link():
    graph = _prompt(image_name="telegram-input.png")
    assert graph["12"] == {
        "class_type": "LoadImage",
        "inputs": {"image": "telegram-input.png"},
    }
    assert graph["7"]["inputs"]["start_image"] == ["12", 0]


def test_dimensions_must_be_divisible_by_16():
    with pytest.raises(ValueError, match="divisible by 16"):
        _prompt(width=641)


def test_frame_count_must_be_one_mod_four():
    with pytest.raises(ValueError, match="1 mod 4"):
        _prompt(frames=50)


def test_presets_are_bounded_and_quality_is_not_default():
    assert video.PRESETS["smoke"]["steps"] == 4
    assert video.PRESETS["fast"]["width"] == 640
    assert video.PRESETS["balanced"]["width"] == 832
    assert video.PRESETS["quality"]["width"] == 1280
    assert video.parser().parse_args([]).preset == "fast"


def test_find_video_record_handles_comfyui_ui_output_shape():
    entry = {
        "outputs": {
            "11": {
                "videos": [
                    {
                        "filename": "Wan22_00001_.mp4",
                        "subfolder": "hermes-video",
                        "type": "output",
                    }
                ]
            }
        }
    }
    record = video._find_video_record(entry)
    assert record is not None
    assert record["filename"].endswith(".mp4")


def test_preflight_reports_missing_nodes_and_models(monkeypatch):
    object_info = {
        name: {"input": {"required": {}}}
        for name in video.REQUIRED_NODES
        if name != "SaveVideo"
    }
    object_info["UNETLoader"] = {
        "input": {"required": {"unet_name": [[video.MODEL_NAME], {}]}}
    }
    object_info["CLIPLoader"] = {
        "input": {"required": {"clip_name": [[video.TEXT_ENCODER], {}]}}
    }
    object_info["VAELoader"] = {
        "input": {"required": {"vae_name": [["other.safetensors"], {}]}}
    }

    def fake_request(_base, path, **_kwargs):
        if path == "/system_stats":
            return {"system": {"os": "posix"}}
        if path == "/object_info":
            return object_info
        raise AssertionError(path)

    monkeypatch.setattr(video, "_request_json", fake_request)
    result = video.preflight("http://127.0.0.1:8188")
    assert result["ok"] is False
    assert result["missing_nodes"] == ["SaveVideo"]
    assert result["missing_models"] == [video.VAE_NAME]


def test_history_error_extracts_execution_failure():
    entry = {
        "status": {
            "messages": [
                ["execution_start", {"prompt_id": "x"}],
                ["execution_error", {"exception_message": "out of memory"}],
            ]
        }
    }
    error = video._history_error(entry)
    assert error is not None
    assert "out of memory" in error
