from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "stage_c" / "validate_hermes_adapter_real.py"
SPEC = importlib.util.spec_from_file_location("stage_c_hermes_real_smoke", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "http://127.0.0.1:8642/v1/toolsets"),
    )


def test_real_smoke_allows_turn_when_no_enabled_concrete_tools(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod.httpx,
        "get",
        lambda *_args, **_kwargs: _response(
            {
                "object": "list",
                "platform": "api_server",
                "data": [
                    {"name": "web", "enabled": False, "tools": ["web_search"]},
                    {"name": "empty", "enabled": True, "tools": []},
                ],
            }
        ),
    )

    mod._assert_real_turn_safe("secret")

    out = capsys.readouterr().out
    assert "PASS: api_server exposes no enabled concrete tools" in out


def test_real_smoke_refuses_turn_when_enabled_tools_exist(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod.httpx,
        "get",
        lambda *_args, **_kwargs: _response(
            {
                "object": "list",
                "platform": "api_server",
                "data": [
                    {
                        "name": "terminal",
                        "enabled": True,
                        "tools": ["terminal", "process"],
                    }
                ],
            }
        ),
    )

    with pytest.raises(mod.SmokeError, match="request-scoped tool disabling"):
        mod._assert_real_turn_safe("secret")

    out = capsys.readouterr().out
    assert "SAFE STOP: real agent turn was NOT executed." in out
    assert "terminal: terminal, process" in out
