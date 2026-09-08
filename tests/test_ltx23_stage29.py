from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_video" / "generate_ltx23_stage29.py"
spec = importlib.util.spec_from_file_location("generate_ltx23_stage29_test", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_integer_second_durations_map_to_ltx_frame_grid():
    assert mod.frames_for_duration(1, 24) == 25
    assert mod.frames_for_duration(2, 24) == 49
    assert mod.frames_for_duration(4, 24) == 97
    assert mod.frames_for_duration(6, 24) == 145
    for seconds in range(1, 7):
        frames = mod.frames_for_duration(seconds, 24)
        assert (frames - 1) % 8 == 0


def test_duration_is_bounded():
    for value in (0, 7):
        try:
            mod.frames_for_duration(value, 24)
        except ValueError:
            pass
        else:
            raise AssertionError("out-of-range duration must fail")


def _assert_tiled_decode(node: dict, samples: list):
    assert node["class_type"] == "VAEDecodeTiled"
    assert node["inputs"] == {
        "samples": samples,
        "vae": ["1", 2],
        "tile_size": 512,
        "overlap": 64,
        "temporal_size": 32,
        "temporal_overlap": 8,
    }


def test_standard_t2v_uses_temporally_tiled_vae_decode():
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
    _assert_tiled_decode(graph["17"], ["16", 0])


def test_hq_t2v_uses_temporally_tiled_vae_decode():
    graph = mod.build_prompt(
        "robot waves",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=True,
    )
    _assert_tiled_decode(graph["26"], ["25", 0])


def test_image_to_video_injects_first_frame_before_sampling():
    graph = mod.build_prompt(
        "robot waves",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=False,
        staged_image_name="stage29_i2v_test.png",
    )
    assert graph["30"] == {"class_type": "LoadImage", "inputs": {"image": "stage29_i2v_test.png"}}
    assert graph["31"]["class_type"] == "LTXVPreprocess"
    assert graph["32"]["class_type"] == "LTXVImgToVideoInplace"
    assert graph["32"]["inputs"]["latent"] == ["7", 0]
    assert graph["32"]["inputs"]["strength"] == 1.0
    assert graph["10"]["inputs"]["video_latent"] == ["32", 0]
    _assert_tiled_decode(graph["17"], ["16", 0])


def test_hq_i2v_reinjects_first_frame_after_latent_upscale_and_tiles_decode():
    graph = mod.build_prompt(
        "robot waves",
        width=640,
        height=384,
        frames=97,
        fps=24,
        seed=1,
        negative="bad",
        upscale_2x=True,
        staged_image_name="stage29_i2v_test.png",
    )
    assert graph["33"]["class_type"] == "LTXVImgToVideoInplace"
    assert graph["33"]["inputs"]["latent"] == ["18", 0]
    assert graph["19"]["inputs"]["video_latent"] == ["33", 0]
    _assert_tiled_decode(graph["26"], ["25", 0])


def test_preflight_requires_core_tiled_decode(monkeypatch):
    monkeypatch.setattr(
        mod.base,
        "preflight",
        lambda url, require_upscale=False: {"ok": True, "missing_nodes": [], "missing_models": []},
    )
    monkeypatch.setattr(
        mod.base,
        "req_json",
        lambda *args, **kwargs: {
            "LoadImage": {},
            "LTXVPreprocess": {},
            "LTXVImgToVideoInplace": {},
            "VAEDecodeTiled": {},
            "LatentUpscaleModelLoader": {},
            "LTXVLatentUpsampler": {},
        },
    )
    monkeypatch.setattr(mod.base, "_options", lambda *args, **kwargs: {mod.base.UPSCALER})
    out = mod.preflight("http://127.0.0.1:8188", require_upscale=True, require_i2v=True)
    assert out["ok"] is True
    assert out["missing_nodes"] == []
    assert out["vae_decode"] == "VAEDecodeTiled"
    assert out["vae_temporal_size"] == 32


def test_preflight_fails_without_core_tiled_decode(monkeypatch):
    monkeypatch.setattr(
        mod.base,
        "preflight",
        lambda url, require_upscale=False: {"ok": True, "missing_nodes": [], "missing_models": []},
    )
    monkeypatch.setattr(mod.base, "req_json", lambda *args, **kwargs: {})
    out = mod.preflight("http://127.0.0.1:8188")
    assert out["ok"] is False
    assert "VAEDecodeTiled" in out["missing_nodes"]
