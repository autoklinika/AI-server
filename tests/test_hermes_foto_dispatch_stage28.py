from __future__ import annotations

import importlib.util
import json
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


def _job(tmp_path: Path, *, prompt: str, input_image: str | None = None) -> Path:
    job = tmp_path / "job"
    job.mkdir()
    (job / "request.json").write_text(
        json.dumps(
            {
                "job_id": "test",
                "prompt": prompt,
                "target": "telegram:123",
                "input_image": input_image,
            }
        ),
        encoding="utf-8",
    )
    return job


def test_edit_like_text_without_image_is_stopped_before_flux(monkeypatch, tmp_path):
    job = _job(tmp_path, prompt="Zmień kolor obudowy na czerwony, resztę pozostaw bez zmian.")
    monkeypatch.setattr(
        mod,
        "compile_image_prompt",
        lambda prompt, has_input: {
            "qwen_used": True,
            "intent": "edit",
            "prompt": "Change the enclosure color to red and keep everything else unchanged.",
            "failure_reason": None,
            "elapsed_seconds": 0.1,
        },
    )
    sent = []
    monkeypatch.setattr(mod, "_send", lambda target, message, **kwargs: sent.append((target, message)))

    def should_not_render(*args, **kwargs):
        raise AssertionError("FLUX must not start for edit intent without input image")

    monkeypatch.setattr(mod, "_run_generator", should_not_render)
    assert mod.worker(job) == 3
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    assert result["needs_input_image"] is True
    assert result["qwen_intent"] == "edit"
    assert any("nie dostało zdjęcia" in message for _, message in sent)


def test_generate_uses_qwen_effective_prompt(monkeypatch, tmp_path):
    job = _job(tmp_path, prompt="Mały czerwony robot przy stole elektronika.")
    effective = "A small red robot sits at an electronics workbench, realistic workshop photo, balanced lighting."
    monkeypatch.setattr(
        mod,
        "compile_image_prompt",
        lambda prompt, has_input: {
            "qwen_used": True,
            "intent": "generate",
            "prompt": effective,
            "failure_reason": None,
            "elapsed_seconds": 0.2,
        },
    )
    seen = {}
    output = tmp_path / "out.png"
    output.write_bytes(b"png")

    def fake_generator(request, log):
        seen["prompt"] = request["prompt"]
        return output

    sent = []
    monkeypatch.setattr(mod, "_run_generator", fake_generator)
    monkeypatch.setattr(mod, "_send", lambda target, message, **kwargs: sent.append((target, message)))
    assert mod.worker(job) == 0
    assert seen["prompt"] == effective
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["qwen_used"] is True
    assert result["effective_prompt"] == effective
    assert sent[-1][1] == f"MEDIA:{output}"


def test_qwen_failure_stops_before_flux(monkeypatch, tmp_path):
    job = _job(tmp_path, prompt="Mały robot.")
    monkeypatch.setattr(
        mod,
        "compile_image_prompt",
        lambda prompt, has_input: {
            "qwen_used": False,
            "intent": "unknown",
            "prompt": prompt,
            "failure_reason": "timeout",
            "elapsed_seconds": 90.0,
        },
    )
    monkeypatch.setattr(mod, "_send", lambda *args, **kwargs: None)

    def should_not_render(*args, **kwargs):
        raise AssertionError("FLUX must not start after Qwen prompt compiler failure")

    monkeypatch.setattr(mod, "_run_generator", should_not_render)
    assert mod.worker(job) == 1
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["qwen_failure_reason"] == "timeout"
    assert "render nie został uruchomiony" in result["error"]
