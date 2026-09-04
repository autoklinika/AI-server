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


def test_foto_skill_uses_validated_local_flux_pipeline_only():
    text = SKILL.read_text(encoding="utf-8")

    assert "narzędzia `terminal` dokładnie jeden raz" in text
    assert "lokalny ComfyUI + FLUX.2 Klein 4B" in text
    assert "Nie używaj `image_generate`" in text
    assert "Wrapper sam wysyła wygenerowany PNG do Telegrama" in text
    assert "jeden poprawnie zacytowany argument powłoki" in text
