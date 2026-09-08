from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/local_image/hermes_foto_dispatch.py"
spec = importlib.util.spec_from_file_location("hermes_foto_dispatch_stage28", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_routing_target_with_thread():
    env = {
        "HERMES_SESSION_PLATFORM": "telegram",
        "HERMES_SESSION_CHAT_ID": "12345",
        "HERMES_SESSION_THREAD_ID": "77",
    }
    assert mod.routing_target(env) == "telegram:12345:77"


def test_routing_target_requires_exact_chat():
    try:
        mod.routing_target({"HERMES_SESSION_PLATFORM": "telegram"})
    except mod.FotoDispatchError as exc:
        assert "CHAT_ID" in str(exc)
    else:
        raise AssertionError("missing chat id must fail closed")


def test_input_image_accepts_exact_existing_absolute_path(tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes(b"x")
    assert mod._input_image({"HERMES_FOTO_INPUT_IMAGE": str(image)}) == str(image)


def test_extract_image_path_from_generator_prefix(tmp_path):
    image = tmp_path / "result.png"
    image.write_bytes(b"png")
    out = f"noise\nImage: {image}\nDONE\n"
    assert mod.extract_image_path(out) == image


def test_extract_image_path_from_json(tmp_path):
    image = tmp_path / "result.webp"
    image.write_bytes(b"webp")
    out = '{"ok": true, "output": "%s"}\n' % image
    assert mod.extract_image_path(out) == image


def test_empty_prompt_returns_usage_without_route_lookup(monkeypatch):
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_CHAT_ID", raising=False)
    assert mod.dispatch("   ").startswith("Użycie: /foto")
