from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    ROOT / "deploy/stage-c/build_release.sh",
    ROOT / "deploy/stage-c/activate_release.sh",
    ROOT / "deploy/stage-c/rollback_release.sh",
    ROOT / "deploy/stage-c/cutover_media_wrapper.sh",
    ROOT / "deploy/stage-c/rollback_media_wrapper.sh",
]


def test_stage_c_deploy_scripts_are_valid_bash() -> None:
    for script in SCRIPTS:
        result = subprocess.run(
            ["bash", "-n", str(script)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert result.returncode == 0, f"{script}: {result.stdout}"


def test_stage_c_builder_uses_exact_committed_source_not_stage_a_reconstruction() -> None:
    text = (ROOT / "deploy/stage-c/build_release.sh").read_text(encoding="utf-8")
    assert 'SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD)"' in text
    assert 'git -C "$ROOT" archive "$SOURCE_SHA"' in text
    assert "reconstruct_ai_bridge_baseline.sh" not in text
    assert "src/ai_bridge/gateway" in text
    assert "pyproject.toml" in text


def test_stage_c_cutover_rolls_back_to_previous_release_not_legacy() -> None:
    activate = (ROOT / "deploy/stage-c/activate_release.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "deploy/stage-c/rollback_release.sh").read_text(encoding="utf-8")

    assert "previous-release" in activate
    assert "previous-release" in rollback
    assert "rollback_to_legacy" not in activate
    assert "rollback_to_legacy" not in rollback
    assert "AI Gateway idle (0/0/0)" in activate
    assert "AI Gateway idle (0/0/0)" in rollback


def test_media_wrapper_cutover_is_separate_and_release_managed() -> None:
    cutover = (ROOT / "deploy/stage-c/cutover_media_wrapper.sh").read_text(
        encoding="utf-8"
    )
    rollback = (ROOT / "deploy/stage-c/rollback_media_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "/opt/ai-platform/current/services/ai-bridge" in cutover
    assert "generate_ltx23_stage30.py" in cutover
    assert "STAGE_C_PROVIDER_MEDIA_WRAPPER=1" in cutover
    assert "ComfyUI queue empty" in cutover
    assert "systemctl restart hermes" not in cutover.lower()
    assert "systemctl restart comfyui" not in cutover.lower()
    assert "generate-video-ltx23.pre-stage-c" in rollback
