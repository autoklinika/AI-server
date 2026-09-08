from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CUTOVER = ROOT / "tools" / "cutover_hermes_ltx23_prompt_stage27.sh"
ROLLBACK = ROOT / "tools" / "rollback_hermes_ltx23_prompt_stage27.sh"


def test_cutover_requires_real_local_qwen_preflight_and_installs_stage27():
    text = CUTOVER.read_text(encoding="utf-8")
    assert "--qwen-preflight" in text
    assert "hermes_video_dispatch_stage27.py" in text
    assert "qwen_prompt_compiler.py" in text
    assert "ai-gateway.service" in text
    assert "restoring Stage26 dispatcher" in text


def test_rollback_restores_stage26_dispatcher_and_refuses_later_changes():
    text = ROLLBACK.read_text(encoding="utf-8")
    assert "REFUSE TO CLOBBER LATER CHANGES" in text
    assert "hermes_video_dispatch.py" in text
    assert "Stage27 rolled back" in text
