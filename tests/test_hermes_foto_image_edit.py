from pathlib import Path


GENERATOR = Path("deploy/local-bin/generate-image-edit")
TELEGRAM_WRAPPER = Path("deploy/local-bin/generate-image-edit-telegram")
INSTALLER = Path("tools/install_hermes_foto_image_edit_stage25.sh")
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


def test_stage25_installer_patches_only_foto_current_turn_media_bridge():
    text = INSTALLER.read_text(encoding="utf-8")

    assert 'HERMES_EXPECTED_SHA="254158f4530cada634c4ef8f4cff93257c5b4f77"' in text
    assert 'if cmd_key == "/foto":' in text
    assert 'getattr(event, "media_urls", None)' in text
    assert "_event_media_is_image(event, _idx)" in text
    assert "[HERMES_FOTO_INPUT_IMAGE]" in text
    assert "path={_foto_path}" in text
    assert "event.media_urls = []" in text
    assert "event.media_types = []" in text
    assert "event.media_text_inlined = []" in text
    assert "expected exactly one slash-skill user_instruction anchor" in text


def test_stage25_has_full_rollback_to_previous_text_to_image_state():
    install = INSTALLER.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")

    assert 'BACKUP_DIR="${HERMES_HOME}/stage25-foto-edit-backup"' in install
    assert 'cp --preserve=mode,timestamps "$HERMES_RUN" "$BACKUP_DIR/run.py"' in install
    assert 'cp --preserve=mode,timestamps "$SKILL_DEST" "$BACKUP_DIR/SKILL.md"' in install
    assert 'cp --preserve=mode,timestamps "$BACKUP_DIR/run.py" "$HERMES_RUN"' in rollback
    assert 'install -m 0644 "$BACKUP_DIR/SKILL.md" "$SKILL_DEST"' in rollback
    assert "Stage-25 rollback completed" in rollback
