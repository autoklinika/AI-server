from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / "deploy" / "autopilot"


def test_all_stage_specs_exist():
    for stage in "efgh":
        path = AUTO / "prompts" / f"stage_{stage}.md"
        assert path.is_file()
        assert f"Stage {stage.upper()}" in path.read_text(encoding="utf-8")


def test_notifier_is_send_only():
    text = (AUTO / "notify_telegram.py").read_text(encoding="utf-8")
    assert "sendMessage" in text
    assert "getUpdates" not in text.replace("never calls getUpdates", "")


def test_supervisor_has_expected_stage_order():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert "for stage in E F G H" in text


def test_runner_requires_review_and_full_rollback_cycle():
    text = (AUTO / "run_stage.sh").read_text(encoding="utf-8")
    assert "AUTOPILOT_REVIEW=PASS" in text
    for script in (
        "20_cutover.sh",
        "30_smoke.sh",
        "40_rollback.sh",
        "50_rollback_smoke.sh",
        "60_reactivate.sh",
        "70_reactivate_smoke.sh",
    ):
        assert script in text
    assert "emergency_rollback" in text


def test_chat_discovery_does_not_consume_updates():
    text = (AUTO / "discover_telegram_chats.py").read_text(encoding="utf-8")
    assert "getChat" in text
    assert "getUpdates" not in text
