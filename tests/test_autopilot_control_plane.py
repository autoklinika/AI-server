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


def test_bootstrap_uses_tmux_not_systemd_for_codex_supervisor():
    text = (AUTO / "bootstrap_stage_eh.sh").read_text(encoding="utf-8")
    assert "tmux new-session" in text
    assert "systemctl --user start ai-stage-eh-agent.service" not in text
    assert "codex" in text


def test_bootstrap_disables_legacy_systemd_launcher():
    text = (AUTO / "bootstrap_stage_eh.sh").read_text(encoding="utf-8")
    assert "disable --now ai-stage-eh-agent.service" in text
    assert "LEGACY_UNIT" in text


def test_runner_waits_for_registered_ci_by_sha():
    text = (AUTO / "run_stage.sh").read_text(encoding="utf-8")
    assert "wait_commit_ci" in text
    assert "workflow did not register" in text
    assert "gh pr checks" not in text


def test_pre_prod_resume_is_fail_closed():
    text = (AUTO / "resume_pre_prod.sh").read_text(encoding="utf-8")
    assert 'state" == "PRE_PROD_CI"' in text
    assert "worktree is dirty; refusing resume" in text
    assert "AI_AUTOPILOT_RESUME_STAGE" in text
    assert "git reset" not in text


def test_master_requires_explicit_resume_stage():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert "AI_AUTOPILOT_RESUME_STAGE" in text
    assert "--resume-pre-prod" in text
