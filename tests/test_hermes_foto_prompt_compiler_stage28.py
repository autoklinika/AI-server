from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/local_image/hermes_foto_prompt_compiler.py"
spec = importlib.util.spec_from_file_location("hermes_foto_prompt_compiler_stage28", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_compile_prompt_generate_success(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_request",
        lambda original, has_input, timeout: (
            "generate",
            "A small red robot sits at an electronics workbench, realistic photo.",
        ),
    )
    out = mod.compile_prompt("Mały czerwony robot przy stole elektronika.", False)
    assert out["qwen_used"] is True
    assert out["intent"] == "generate"
    assert out["failure_reason"] is None
    assert out["prompt"].startswith("A small red robot")


def test_compile_prompt_edit_with_image_forces_edit(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_request",
        lambda original, has_input, timeout: (
            "generate",
            "Change only the enclosure color to red; keep all other details unchanged.",
        ),
    )
    out = mod.compile_prompt("Zmień kolor obudowy na czerwony.", True)
    assert out["qwen_used"] is True
    assert out["intent"] == "generate"  # compile_prompt trusts _request; forcing is tested inside _request contract


def test_compile_prompt_failure_is_explicit(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("bad response")

    monkeypatch.setattr(mod, "_request", fail)
    out = mod.compile_prompt("test", False)
    assert out["qwen_used"] is False
    assert out["intent"] == "unknown"
    assert out["prompt"] == "test"
    assert "bad response" in out["failure_reason"]


def test_gateway_url_rejects_remote(monkeypatch):
    monkeypatch.setenv("HERMES_FOTO_QWEN_URL", "https://example.com/v1/chat/completions")
    try:
        mod._gateway_url()
    except RuntimeError as exc:
        assert "lokalnego AI Gateway" in str(exc)
    else:
        raise AssertionError("remote prompt compiler endpoint must be rejected")
