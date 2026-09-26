import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "deploy/discord-technical/gate.py"


def gate_module():
    spec = importlib.util.spec_from_file_location("discord_technical_gate_test", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_discord_gate_is_hermes_only_and_has_planned_rollback_contract():
    text = GATE_PATH.read_text()
    assert '"hermes-gateway.service"' in text
    assert "DISCORD_TECHNICAL_ROLLBACK_SMOKE=PASS" in text
    assert "force_restore_and_start" in text
    assert "recover_to_baseline" in text
    assert "policy_smoke.py" in text
    for forbidden in (
        'restart", "ai-gateway.service',
        'restart", "ai-bridge.service',
        'restart", "comfyui.service',
        'restart", "ollama.service',
        'stop", "ai-gateway.service',
        'stop", "ai-bridge.service',
    ):
        assert forbidden not in text


def test_policy_smoke_uses_real_knowledge_and_checks_channel_contract():
    text = (ROOT / "deploy/discord-technical/policy_smoke.py").read_text()
    assert "Jaki SPN był przy naprawie Hatz?" in text
    assert "structured-generation" in text
    assert 'item.get("capability") == "chat"' in text
    assert "telegram_passthrough" in text
    assert "discord_media_blocked" in text
    assert "discord_voice_command_passthrough" in text
    assert "discord_voice_rag" in text
    assert "_tts_artifact" in text


def test_candidate_contract_requires_discord_technical_markers(monkeypatch, tmp_path):
    gate = gate_module()
    candidate = tmp_path / "plugin"
    candidate.mkdir()
    source = (ROOT / "integrations/hermes/ai-platform-messaging/__init__.py").read_text()
    manifest = (ROOT / "integrations/hermes/ai-platform-messaging/plugin.yaml").read_text()
    (candidate / "__init__.py").write_text(source)
    (candidate / "plugin.yaml").write_text(manifest)
    monkeypatch.setattr(gate, "CANDIDATE", candidate)
    monkeypatch.setattr(gate, "run", lambda *args, **kwargs: "")
    gate.candidate_contract()


def test_recovery_works_when_gateway_is_already_stopped(monkeypatch, tmp_path):
    gate = gate_module()
    state_root = tmp_path / "state"
    live = tmp_path / "live"
    baseline = state_root / ("a" * 40) / "baseline-plugin"
    baseline.mkdir(parents=True)
    live.mkdir()
    for root, tag in ((baseline, "baseline"), (live, "candidate")):
        (root / "__init__.py").write_text(tag)
        (root / "plugin.yaml").write_text(tag)

    monkeypatch.setattr(gate, "STATE_ROOT", state_root)
    monkeypatch.setattr(gate, "LIVE", live)
    monkeypatch.setattr(gate, "gateway_service_active", lambda: False)
    calls = []

    def restore(source):
        calls.append(Path(source))
        for name in gate.FILES:
            (live / name).write_bytes((Path(source) / name).read_bytes())
        return {"pid": 123}

    monkeypatch.setattr(gate, "force_restore_and_start", restore)
    gate.recover_to_baseline("a" * 40)
    assert calls == [baseline]
    assert gate.hashes(live) == gate.hashes(baseline)


def test_all_gate_recovers_baseline_when_candidate_smoke_fails(monkeypatch):
    gate = gate_module()
    actions = []
    monkeypatch.setattr(gate, "preflight", lambda sha: actions.append("preflight") or {})
    monkeypatch.setattr(gate, "cutover", lambda sha: actions.append("cutover"))

    def fail_smoke(sha, name):
        actions.append(name)
        raise RuntimeError("controlled smoke failure")

    monkeypatch.setattr(gate, "run_policy_smoke", fail_smoke)
    monkeypatch.setattr(gate, "recover_to_baseline", lambda sha: actions.append("recover"))
    monkeypatch.setattr(gate, "rollback_smoke", lambda sha: actions.append("rollback-smoke"))

    with pytest.raises(RuntimeError, match="controlled smoke failure"):
        gate.all_gate("b" * 40)

    assert actions == [
        "preflight",
        "cutover",
        "smoke",
        "recover",
        "rollback-smoke",
    ]
