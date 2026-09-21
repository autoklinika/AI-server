from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "stage_c"
    / "validate_hermes_adapter_isolated.py"
)
SPEC = importlib.util.spec_from_file_location("stage_c_hermes_isolated_smoke", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_isolated_config_has_no_agent_tools_or_mcp() -> None:
    config = mod._minimal_config()

    assert config["model"]["provider"] == "custom"
    assert config["model"]["base_url"] == mod.HERMES_LLM_ROUTE
    assert config["model"]["default"] == mod.MODEL
    assert config["platform_toolsets"]["api_server"] == []
    assert config["toolsets"] == []
    assert config["mcp_servers"] == {}
    assert config["memory"]["memory_enabled"] is False
    assert config["memory"]["user_profile_enabled"] is False
    assert config["agent"]["max_turns"] == 1
    assert config["agent"]["reasoning_effort"] == "none"


def test_isolated_env_does_not_inherit_messaging_or_provider_secrets(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "provider-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/test")

    env = mod._isolated_env(tmp_path, 18642, "isolated-secret")

    assert env["HERMES_HOME"] == str(tmp_path)
    assert env["API_SERVER_ENABLED"] == "true"
    assert env["API_SERVER_HOST"] == "127.0.0.1"
    assert env["API_SERVER_PORT"] == "18642"
    assert env["API_SERVER_KEY"] == "isolated-secret"
    assert env["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "DISCORD_BOT_TOKEN" not in env
    assert "OPENROUTER_API_KEY" not in env


def test_enabled_concrete_tools_returns_only_enabled_nonempty_rows(monkeypatch) -> None:
    def fake_get(*_args, **_kwargs):
        return httpx.Response(
            200,
            json={
                "object": "list",
                "platform": "api_server",
                "data": [
                    {"name": "web", "enabled": False, "tools": ["web_search"]},
                    {"name": "empty", "enabled": True, "tools": []},
                    {
                        "name": "terminal",
                        "enabled": True,
                        "tools": ["terminal", "process_manage"],
                    },
                ],
            },
            request=httpx.Request("GET", "http://127.0.0.1:18642/v1/toolsets"),
        )

    monkeypatch.setattr(mod.httpx, "get", fake_get)

    assert mod._enabled_concrete_tools("http://127.0.0.1:18642", "secret") == [
        ("terminal", ["terminal", "process_manage"])
    ]
