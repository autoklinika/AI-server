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
    assert "CI_GATE_TIMEOUT" in text
    assert "gh pr checks" not in text


def test_pre_prod_resume_is_fail_closed():
    text = (AUTO / "resume_pre_prod.sh").read_text(encoding="utf-8")
    assert "PRE_PROD_CI|PRODUCTION:00_preflight.sh" in text
    assert "worktree is dirty; refusing resume" in text
    assert "AI_AUTOPILOT_RESUME_STAGE" in text
    assert "git reset" not in text


def test_master_requires_explicit_resume_stage():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert "AI_AUTOPILOT_RESUME_STAGE" in text
    assert "--resume-pre-prod" in text


def test_readonly_preflight_failure_returns_to_resumable_boundary():
    text = (AUTO / "run_stage.sh").read_text(encoding="utf-8")
    assert "for attempt in 1 2 3" in text
    assert "set_state PRE_PROD_CI" in text
    assert "exit 31" in text
    assert "return 31" not in text


def test_resume_accepts_legacy_readonly_preflight_state_only():
    text = (AUTO / "resume_pre_prod.sh").read_text(encoding="utf-8")
    assert "PRODUCTION:00_preflight.sh" in text
    assert "PRE_PROD_CI|PRODUCTION:00_preflight.sh" in text


def test_ci_gate_uses_resilient_polling_not_watch():
    text = (AUTO / "run_stage.sh").read_text(encoding="utf-8")
    assert "gh run watch" not in text
    assert "gh run view" in text
    assert "CI_GATE_PASS" in text
    assert "transient_errors" in text


def test_readonly_preflight_retries_and_exits_resumable():
    text = (AUTO / "run_stage.sh").read_text(encoding="utf-8")
    assert "for attempt in 1 2 3" in text
    assert "exit 31" in text
    assert "return 31" not in text
    assert "PREFLIGHT_FAIL" in text
    assert "AUTOPILOT_ROOT_DENY" in text


def test_blocked_notification_can_include_safe_reason():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert 'reason="$(cat "$STATE_DIR/stage-$stage/reason"' in text
    assert "reason=$reason" in text


def test_privilege_bridge_is_narrow_and_sha_bound():
    text = (AUTO / "root_executor.sh").read_text(encoding="utf-8")
    assert 'WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-eh"' in text
    assert 'expected_branch="agent/stage-$stage_lc"' in text
    assert 'remote_sha' in text
    assert 'merge-base --is-ancestor origin/main' in text
    assert 'status --porcelain --untracked-files=all' in text
    assert 'AUTOPILOT_ROOT_DENY=' in text
    assert 'eval ' not in text
    for step in (
        "00_preflight.sh",
        "10_build_install.sh",
        "20_cutover.sh",
        "30_smoke.sh",
        "40_rollback.sh",
        "50_rollback_smoke.sh",
        "60_reactivate.sh",
        "70_reactivate_smoke.sh",
        "90_finalize.sh",
    ):
        assert step in text


def test_runner_routes_production_through_root_bridge():
    text = (AUTO / "run_stage.sh").read_text(encoding="utf-8")
    assert 'ROOT_BRIDGE="/usr/local/libexec/ai-platform/autopilot-root-exec"' in text
    assert 'sudo -n "$ROOT_BRIDGE" "$STAGE" "$name" "$expected_sha"' in text
    assert 'PRIVILEGE_BRIDGE_REQUIRED' in text
    assert 'run_root_step 40_rollback.sh' in text
    assert 'run_root_step 50_rollback_smoke.sh' in text


def test_resume_and_bootstrap_require_privilege_bridge():
    for name in ("resume_pre_prod.sh", "bootstrap_stage_eh.sh"):
        text = (AUTO / name).read_text(encoding="utf-8")
        assert "AUTOPILOT_ROOT_BRIDGE=READY" in text
        assert "install_privilege_bridge.sh" in text


def test_privilege_installer_uses_root_owned_helper_and_sudoers():
    text = (AUTO / "install_privilege_bridge.sh").read_text(encoding="utf-8")
    assert "/usr/local/libexec/ai-platform/autopilot-root-exec" in text
    assert "/etc/sudoers.d/ai-platform-autopilot" in text
    assert "NOPASSWD" in text
    assert "visudo" in text
    assert 'branch_name' in text and '"main"' in text
    assert "main worktree must be clean" in text


def test_master_self_retries_only_safe_preprod_failures():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert "WAITING_SAFE_RETRY" in text
    assert '[[ "$stage_state" == "PRE_PROD_CI" ]]' in text
    assert '[[ "$rc" =~ ^(31|91|94)$ ]]' in text
    assert 'sleep "$retry_delay"' in text
    assert "retry_delay=300" in text
    assert "Produkcja nie została zmieniona." in text


def test_stale_preprod_is_auto_resumable_but_production_is_not():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert 'PRE_PROD_CI)' in text
    assert 'RESUME_STAGE="$stage"' in text
    assert 'PRODUCTION_MUTATING|PRODUCTION:20_cutover.sh' in text
    assert "recover_interrupted_production" in text


def test_master_captures_runner_rc_in_else_not_after_if():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert 'else\n      rc=$?\n    fi' in text
    assert 'fi\n\n    rc=$?' not in text


def test_master_clears_reason_before_every_runner_attempt():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    clear = 'rm -f "$STATE_DIR/stage-$stage/reason"'
    runner = 'if "$RUNNER" "${runner_args[@]}"; then'
    assert clear in text
    assert text.index(clear) < text.index(runner)


def test_restart_recovery_uses_privilege_bridge():
    text = (AUTO / "stage_eh_master.sh").read_text(encoding="utf-8")
    assert 'sudo -n "$ROOT_BRIDGE" "$stage" 40_rollback.sh "$expected_sha"' in text
    assert 'sudo -n "$ROOT_BRIDGE" "$stage" 50_rollback_smoke.sh "$expected_sha"' in text


def test_resume_regenerates_review_prompt_from_current_stage_spec():
    text = (AUTO / 'run_stage.sh').read_text(encoding='utf-8')
    marker = 'codex-review-resume.log'
    idx = text.index(marker)
    before = text[:idx]
    assert 'cat > "$STAGE_STATE/review.prompt" <<EOF' in before
    assert 'cat "$SPEC" >> "$STAGE_STATE/review.prompt"' in before


def test_stage_e_policy_defers_external_inbound_multiuser_to_stage_f():
    text = (AUTO / 'prompts' / 'stage_e.md').read_text(encoding='utf-8')
    assert 'correlated multi-client Hermes-namespace requests' in text
    assert 'successful outbound delivery' in text
    assert 'Full fresh inbound multiuser/user-path validation' in text
    assert 'mandatory in Stage F' in text


def test_privilege_bridge_allows_dedicated_worktrees_through_stage_j():
    text = (AUTO / 'root_executor.sh').read_text(encoding='utf-8')
    assert '[[ "$stage" =~ ^[EFGHIJLM]$ ]]' in text
    assert 'M) WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-m"' in text
    assert 'E|F|G|H) WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-eh"' in text
    assert 'I) WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-i"' in text
    assert 'J) WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-j"' in text
    assert 'L) WORKTREE="$ALLOWED_HOME/agent-worktrees/stage-l"' in text
    assert 'expected_branch="agent/stage-$stage_lc"' in text
    assert 'status --porcelain --untracked-files=all' in text
    assert 'merge-base --is-ancestor origin/main' in text
    assert 'bash "$script"' in text
    assert 'eval ' not in text
