from __future__ import annotations

from pathlib import Path
import subprocess

from ai_bridge.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
STAGE_D_SCRIPTS = [
    ROOT / "deploy/stage-d/build_release.sh",
    ROOT / "deploy/stage-d/install_release.sh",
    ROOT / "deploy/stage-d/validate_installed_release.sh",
    ROOT / "deploy/stage-d/activate_release.sh",
    ROOT / "deploy/stage-d/rollback_release.sh",
    ROOT / "deploy/stage-d/install_canonical_systemd.sh",
    ROOT / "deploy/stage-d/restore_systemd_compat.sh",
    ROOT / "deploy/stage-d/apply_gateway_default_policy.sh",
    ROOT / "deploy/stage-d/restore_gateway_policy.sh",
]


def test_gateway_is_the_default_analysis_route_with_explicit_recovery_bypass() -> None:
    assert Settings.model_fields["analysis_use_gateway"].default is True
    assert Settings(analysis_use_gateway=False).analysis_use_gateway is False


def test_example_env_uses_gateway_by_default() -> None:
    text = (ROOT / "deploy/ai-bridge.env.example").read_text(encoding="utf-8")
    assert "AI_BRIDGE_ANALYSIS_USE_GATEWAY=true" in text
    assert "recovery/debug compatibility bypass" in text


def test_canonical_systemd_units_are_release_managed() -> None:
    expected = {
        "ai-bridge.service": "/opt/ai-platform/current/services/ai-bridge",
        "ai-gateway.service": "/opt/ai-platform/current/services/ai-gateway",
        "ai-bridge-analysis.service": "/opt/ai-platform/current/services/ai-bridge",
    }
    for name, release_path in expected.items():
        text = (ROOT / "deploy/systemd" / name).read_text(encoding="utf-8")
        assert release_path in text
        assert "/opt/ai-bridge" not in text
        assert "/opt/ai-gateway" not in text


def test_analysis_systemd_requires_gateway_and_has_no_url_override() -> None:
    text = (ROOT / "deploy/systemd/ai-bridge-analysis.service").read_text(
        encoding="utf-8"
    )
    assert "Requires=ai-gateway.service" in text
    assert "After=network-online.target postgresql.service ai-gateway.service" in text
    assert "AI_BRIDGE_OLLAMA_URL=" not in text


def test_stage_d_scripts_are_valid_bash() -> None:
    for script in STAGE_D_SCRIPTS:
        result = subprocess.run(
            ["bash", "-n", str(script)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert result.returncode == 0, f"{script}: {result.stdout}"


def test_stage_d_builder_allows_gateway_changes_and_has_rich_manifest() -> None:
    text = (ROOT / "deploy/stage-d/build_release.sh").read_text(encoding="utf-8")
    assert 'SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD)"' in text
    assert "BASE_GATEWAY_SHA" not in text
    assert "scheduler_source_changed: false" not in text
    assert "changed_components:" in text
    assert "contract_versions:" in text
    assert "embedding_provider: 1" in text
    assert "knowledge_backend: 1" in text
    assert "compatibility:" in text
    assert "analysis_direct_ollama_recovery: true" in text
    assert "stage: D" in text


def test_stage_d_install_is_non_activating_and_final_path_venv_aware() -> None:
    text = (ROOT / "deploy/stage-d/install_release.sh").read_text(encoding="utf-8")
    assert 'TARGET="/opt/ai-platform/releases/$RELEASE_ID"' in text
    assert "ln -sfn" not in text
    assert "systemctl restart" not in text
    assert "final-path entrypoint shebangs" in text
    assert "INSTALL STAGE D RELEASE: PASS" in text


def test_stage_d_activation_preserves_idle_gate_and_previous_release_rollback() -> None:
    activate = (ROOT / "deploy/stage-d/activate_release.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "deploy/stage-d/rollback_release.sh").read_text(encoding="utf-8")
    assert "AI Gateway idle (0/0/0)" in activate
    assert "AI Gateway idle (0/0/0)" in rollback
    assert "previous-release" in activate
    assert "previous-release" in rollback
    assert "95-ai-platform-release.conf" in activate
    assert "http://192.168.1.55" not in activate
    assert "http://192.168.1.55" not in rollback


def test_gateway_policy_migration_is_reversible_and_non_restarting() -> None:
    apply = (ROOT / "deploy/stage-d/apply_gateway_default_policy.sh").read_text(
        encoding="utf-8"
    )
    restore = (ROOT / "deploy/stage-d/restore_gateway_policy.sh").read_text(
        encoding="utf-8"
    )
    assert "AI_BRIDGE_ANALYSIS_USE_GATEWAY=true" in apply
    assert "gateway-policy-baseline" in apply
    assert "cp -a" in apply
    assert "systemctl restart" not in apply
    assert "gateway-policy-baseline" in restore
    assert "cp -a" in restore
    assert "systemctl restart" not in restore


def test_canonical_systemd_install_and_restore_are_non_restarting() -> None:
    install = (ROOT / "deploy/stage-d/install_canonical_systemd.sh").read_text(
        encoding="utf-8"
    )
    restore = (ROOT / "deploy/stage-d/restore_systemd_compat.sh").read_text(
        encoding="utf-8"
    )
    assert "systemctl restart" not in install
    assert "systemctl restart" not in restore
    assert "95-ai-platform-release.conf" in install
    assert "95-ai-platform-release.conf" in restore
    assert "systemctl daemon-reload" in install
    assert "systemctl daemon-reload" in restore


def test_ci_protects_main_and_validates_full_stage_d_foundation() -> None:
    text = (ROOT / ".github/workflows/ai-gateway-tests.yml").read_text(
        encoding="utf-8"
    )
    assert "push:" in text
    assert "pull_request:" in text
    assert text.count("- main") >= 2
    assert "Full test suite" in text
    assert "pytest" in text
    assert "Provider and contract tests" in text
    assert "Stage D foundation tests" in text
    assert "deploy/stage-d/build_release.sh" in text
