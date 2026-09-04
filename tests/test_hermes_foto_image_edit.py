from pathlib import Path
import subprocess
import sys


GENERATOR = Path("deploy/local-bin/generate-image-edit")
TELEGRAM_WRAPPER = Path("deploy/local-bin/generate-image-edit-telegram")
PATCHER = Path("tools/patch_hermes_foto_media_path_stage25.py")
INSTALLER = Path("tools/install_hermes_foto_image_edit_stage25.sh")
REPAIR = Path("tools/repair_hermes_foto_image_edit_stage25b.sh")
ROLLBACK = Path("tools/rollback_hermes_foto_image_edit_stage25.sh")


def test_image_edit_generator_is_valid_python_and_uses_local_flux_only():
    text = GENERATOR.read_text(encoding="utf-8")
    compile(text, str(GENERATOR), "exec")

    assert text.startswith("#!/opt/comfyui/venv/bin/python")
    assert 'COMFY = "http://127.0.0.1:8188"' in text
    assert "flux-2-klein-4b-fp8.safetensors" in text
    assert "qwen_3_4b.safetensors" in text
    assert "flux2-vae.safetensors" in text
    assert '"ReferenceLatent"' in text
    assert '"ImageScaleToTotalPixels"' in text
    assert '"VAEEncode"' in text
    assert '"Flux2Scheduler"' in text
    assert '"steps": 4' in text
    assert '"sampler_name": "euler"' in text
    assert '"cfg": 1.0' in text
    assert '"filename_prefix": "Flux2-Klein-Edit"' in text


def test_image_edit_generator_accepts_only_hermes_inbound_image_cache():
    text = GENERATOR.read_text(encoding="utf-8")

    assert 'HERMES_ROOT / "cache" / "images"' in text
    assert 'HERMES_ROOT / "profiles"' in text
    assert 'parts[1:3] == ("cache", "images")' in text
    assert "input image must come from the Hermes inbound image cache" in text
    assert 'SUPPORTED_INPUT_EXTS = {".png", ".jpg", ".jpeg", ".webp"}' in text
    assert "resolve(strict=True)" in text


def test_image_edit_generator_stages_unique_comfy_input_and_restores_qwen():
    text = GENERATOR.read_text(encoding="utf-8")

    assert "stage25_foto_edit_" in text
    assert "uuid.uuid4().hex" in text
    assert 'lock_path = "/tmp/generate-image.lock"' in text
    assert "shutil.copy2(input_path, staged_path)" in text
    assert "staged_path.unlink(missing_ok=True)" in text
    assert "restore_qwen()" in text
    assert '"/usr/local/sbin/ollama-preload-qwen36"' in text


def test_telegram_edit_wrapper_sends_only_generated_result():
    text = TELEGRAM_WRAPPER.read_text(encoding="utf-8")

    assert text.startswith("#!/bin/bash")
    assert 'GENERATOR="/usr/local/bin/generate-image-edit"' in text
    assert 'HERMES="/home/harrypotter/.local/bin/hermes"' in text
    assert 'sed -n \'s/^Image[[:space:]]*:[[:space:]]*//p\'' in text
    assert '"$HERMES" send --to telegram' in text
    assert "Przerobione lokalnie przez FLUX.2 Klein MEDIA:$IMAGE" in text


def _two_anchor_fixture() -> str:
    # The pinned Hermes file has two identical raw assignments.  Only the
    # second one feeds build_skill_invocation_message(cmd_key, ...).
    return '''def dispatch(event, cmd_key, build_skill_invocation_message):
    if cmd_key == "/plan":
                    user_instruction = event.get_command_args().strip()
                    plan_msg = build_skill_invocation_message("/plan", user_instruction)
    if cmd_key:
                    user_instruction = event.get_command_args().strip()
                    msg = build_skill_invocation_message(
                        cmd_key, user_instruction, task_id="probe"
                    )
                    event.text = msg
'''


def test_stage25_patcher_selects_semantic_skill_anchor_when_two_raw_anchors_exist(tmp_path):
    target = tmp_path / "run.py"
    target.write_text(_two_anchor_fixture(), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PATCHER), "--target", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "semantic slash-skill dispatch" in result.stdout

    patched = target.read_text(encoding="utf-8")
    assert patched.count("AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN") == 1
    assert patched.count("AI_SERVER_STAGE25_FOTO_MEDIA_PATH_END") == 1
    plan_call = patched.index('build_skill_invocation_message("/plan", user_instruction)')
    marker = patched.index("AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN")
    skill_call = patched.index("cmd_key, user_instruction, task_id")
    assert plan_call < marker < skill_call

    # Re-running must be safe and must not duplicate the bridge.
    second = subprocess.run(
        [sys.executable, str(PATCHER), "--target", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert "already present" in second.stdout
    assert target.read_text(encoding="utf-8").count("AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN") == 1


def test_stage25_patcher_fails_closed_if_semantic_anchor_is_ambiguous(tmp_path):
    target = tmp_path / "run.py"
    source = '''def dispatch(event, cmd_key, build_skill_invocation_message):
    if cmd_key:
                    user_instruction = event.get_command_args().strip()
                    msg = build_skill_invocation_message(cmd_key, user_instruction)
    if cmd_key:
                    user_instruction = event.get_command_args().strip()
                    msg = build_skill_invocation_message(cmd_key, user_instruction)
'''
    target.write_text(source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PATCHER), "--target", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "semantic candidates=2" in result.stdout
    assert target.read_text(encoding="utf-8") == source


def test_stage25_installer_patches_only_foto_current_turn_media_bridge():
    text = INSTALLER.read_text(encoding="utf-8")
    patcher = PATCHER.read_text(encoding="utf-8")

    assert 'HERMES_EXPECTED_SHA="254158f4530cada634c4ef8f4cff93257c5b4f77"' in text
    assert 'PATCHER_SOURCE="tools/patch_hermes_foto_media_path_stage25.py"' in text
    assert '--target "$HERMES_RUN" --check-only' in text
    assert '--target "$HERMES_RUN"' in text
    assert "expected exactly one slash-skill user_instruction anchor" not in text
    assert 'if cmd_key == "/foto":' in patcher
    assert 'getattr(event, "media_urls", None)' in patcher
    assert "_event_media_is_image(event, _idx)" in patcher
    assert "[HERMES_FOTO_INPUT_IMAGE]" in patcher
    assert "path={_foto_path}" in patcher
    assert "event.media_urls = []" in patcher
    assert "event.media_types = []" in patcher
    assert "event.media_text_inlined = []" in patcher
    assert "SKILL_CALL_RE" in patcher
    assert "compile(patched" in patcher
    assert "os.replace(tmp_name, path)" in patcher


def test_stage25b_repairs_only_expected_partial_state_and_preserves_backup():
    text = REPAIR.read_text(encoding="utf-8")

    assert 'BACKUP_DIR="${HERMES_HOME}/stage25-foto-edit-backup"' in text
    assert '[ -r "$BACKUP_DIR/run.py" ]' in text
    assert "current.read_bytes() != backup.read_bytes()" in text
    assert "refusing to overwrite an unrelated change" in text
    assert 'PATCHER_SOURCE="tools/patch_hermes_foto_media_path_stage25.py"' in text
    assert '--target "$HERMES_RUN" --check-only' in text
    assert '--target "$HERMES_RUN"' in text
    assert "Original rollback backup preserved" in text
    assert "Stage-25B /foto image-edit repair completed" in text


def test_stage25_has_full_rollback_to_previous_text_to_image_state():
    install = INSTALLER.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")

    assert 'BACKUP_DIR="${HERMES_HOME}/stage25-foto-edit-backup"' in install
    assert 'cp --preserve=mode,timestamps "$HERMES_RUN" "$BACKUP_DIR/run.py"' in install
    assert 'cp --preserve=mode,timestamps "$SKILL_DEST" "$BACKUP_DIR/SKILL.md"' in install
    assert 'cp --preserve=mode,timestamps "$BACKUP_DIR/run.py" "$HERMES_RUN"' in rollback
    assert 'install -m 0644 "$BACKUP_DIR/SKILL.md" "$SKILL_DEST"' in rollback
    assert "Stage-25 rollback completed" in rollback
