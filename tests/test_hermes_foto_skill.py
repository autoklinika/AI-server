from pathlib import Path


SKILL = Path("deploy/hermes/skills/foto/SKILL.md")


def test_foto_skill_is_native_slash_skill_contract():
    text = SKILL.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert "\nname: foto\n" in text
    assert "requires_toolsets: [terminal]" in text
    assert "`/foto`" in text
    assert "/usr/local/bin/generate-image-telegram" in text
    assert "/srv/ai-data/hermes/bin/generate-image-telegram" not in text


def test_foto_skill_keeps_validated_local_text_to_image_path():
    text = SKILL.read_text(encoding="utf-8")

    assert "lokalny ComfyUI + FLUX.2 Klein 4B" in text
    assert "Nie używaj `tool_call`" in text
    assert "`image_generate`" in text
    assert "/usr/local/bin/generate-image-telegram \"<PROMPT>\"" in text
    assert "jako jeden poprawnie zacytowany argument powłoki" in text


def test_foto_skill_supports_exact_current_message_image_edit_path():
    text = SKILL.read_text(encoding="utf-8")

    assert "[HERMES_FOTO_INPUT_IMAGE]" in text
    assert "path=/absolutna/sciezka/do/obrazu" in text
    assert "/usr/local/bin/generate-image-edit-telegram" in text
    assert '--input "<PATH>" --prompt "<PROMPT>"' in text
    assert "Nie szukaj „najnowszego” zdjęcia" in text
    assert "zdjęcia załączonego bezpośrednio do tej samej wiadomości" in text


def test_foto_skill_does_not_claim_reply_only_image_support_yet():
    text = SKILL.read_text(encoding="utf-8")

    assert "nie zakładaj obsługi zdjęcia tylko z historii/reply" in text
