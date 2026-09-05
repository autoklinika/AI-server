from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "tools" / "local_video" / "generate_ltx23.py"
spec = importlib.util.spec_from_file_location("ltx23", PATH)
assert spec and spec.loader
ltx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ltx)


def graph(**kwargs):
    p = dict(prompt="red robot waves", width=640, height=384, frames=49, fps=24, seed=123, negative="bad")
    p.update(kwargs)
    return ltx.build_prompt(**p)


def test_distilled_graph_matches_expected_core_settings():
    g = graph()
    assert g["1"]["inputs"]["ckpt_name"] == ltx.CHECKPOINT
    assert g["2"]["inputs"]["lora_name"] == ltx.DISTILLED_LORA
    assert g["2"]["inputs"]["strength_model"] == 0.5
    assert g["3"]["inputs"]["text_encoder"] == ltx.TEXT_ENCODER
    assert g["11"]["inputs"]["cfg"] == 1.0
    assert g["13"]["inputs"]["sampler_name"] == "euler_ancestral_cfg_pp"
    assert g["14"]["inputs"]["sigmas"] == ltx.DISTILLED_SIGMAS


def test_graph_generates_audio_and_video():
    g = graph()
    assert g["8"]["class_type"] == "LTXVAudioVAELoader"
    assert g["9"]["class_type"] == "LTXVEmptyLatentAudio"
    assert g["10"]["class_type"] == "LTXVConcatAVLatent"
    assert g["16"]["class_type"] == "LTXVSeparateAVLatent"
    assert g["18"]["class_type"] == "LTXVAudioVAEDecode"
    assert g["19"]["inputs"]["audio"] == ["18", 0]
    assert g["20"]["inputs"]["format"] == "mp4"


def test_two_stage_upscale_graph_matches_official_shape():
    g = graph(upscale_2x=True)
    assert g["17"]["class_type"] == "LatentUpscaleModelLoader"
    assert g["17"]["inputs"]["model_name"] == ltx.UPSCALER
    assert g["18"]["class_type"] == "LTXVLatentUpsampler"
    assert g["18"]["inputs"]["samples"] == ["16", 0]
    assert g["19"]["inputs"]["audio_latent"] == ["16", 1]
    assert g["22"]["inputs"]["sampler_name"] == "euler_cfg_pp"
    assert g["23"]["inputs"]["sigmas"] == ltx.UPSCALE_SIGMAS
    assert g["24"]["class_type"] == "SamplerCustomAdvanced"
    assert g["26"]["class_type"] == "LTXVTiledVAEDecode"
    assert g["26"]["inputs"]["horizontal_tiles"] == 2
    assert g["26"]["inputs"]["vertical_tiles"] == 2
    assert g["26"]["inputs"]["overlap"] == 6
    assert g["27"]["class_type"] == "LTXVAudioVAEDecode"
    assert g["28"]["inputs"]["audio"] == ["27", 0]
    assert g["29"]["inputs"]["format"] == "mp4"


def test_dimensions_are_multiple_of_32():
    with pytest.raises(ValueError, match="divisible by 32"):
        graph(width=641)


def test_preflight_detects_missing_model(monkeypatch):
    info = {name: {"input": {"required": {}}} for name in ltx.REQUIRED_NODES}
    info["CheckpointLoaderSimple"] = {"input": {"required": {"ckpt_name": [[ltx.CHECKPOINT], {}]}}}
    info["LTXAVTextEncoderLoader"] = {"input": {"required": {"text_encoder": [["wrong.safetensors"], {}]}}}
    info["LoraLoaderModelOnly"] = {"input": {"required": {"lora_name": [[ltx.DISTILLED_LORA], {}]}}}
    monkeypatch.setattr(ltx, "req_json", lambda *_a, **_kw: info)
    out = ltx.preflight("http://localhost")
    assert out["ok"] is False
    assert out["missing_models"] == [ltx.TEXT_ENCODER]


def test_upscale_preflight_checks_node_and_model(monkeypatch):
    required = ltx.REQUIRED_NODES | ltx.UPSCALE_NODES
    info = {name: {"input": {"required": {}}} for name in required}
    info["CheckpointLoaderSimple"] = {"input": {"required": {"ckpt_name": [[ltx.CHECKPOINT], {}]}}}
    info["LTXAVTextEncoderLoader"] = {"input": {"required": {"text_encoder": [[ltx.TEXT_ENCODER], {}]}}}
    info["LoraLoaderModelOnly"] = {"input": {"required": {"lora_name": [[ltx.DISTILLED_LORA], {}]}}}
    info["LatentUpscaleModelLoader"] = {"input": {"required": {"model_name": [["wrong.safetensors"], {}]}}}
    monkeypatch.setattr(ltx, "req_json", lambda *_a, **_kw: info)
    out = ltx.preflight("http://localhost", require_upscale=True)
    assert out["ok"] is False
    assert out["missing_models"] == [ltx.UPSCALER]


def test_find_video():
    entry = {"outputs": {"20": {"videos": [{"filename": "LTX23_001.mp4", "subfolder": "hermes-video", "type": "output"}]}}}
    assert ltx.find_video(entry)["filename"] == "LTX23_001.mp4"
