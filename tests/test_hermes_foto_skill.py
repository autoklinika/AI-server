from pathlib import Path


SKILL = Path("deploy/hermes/skills/foto/SKILL.md")


def test_foto_skill_is_native_slash_skill_contract():
    text = SKILL.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert "\nname: foto\n" in text
    assert "requires_toolsets: [image_gen]" in text
    assert "`/foto`" in text
    assert "`image_generate`" in text


def test_foto_skill_forces_one_image_and_avoids_unrelated_tools():
    text = SKILL.read_text(encoding="utf-8")

    assert "dokładnie jeden obraz" in text
    assert "musisz** użyć narzędzia `image_generate` dokładnie jeden raz" in text
    assert "nie używaj `terminal`" in text
    assert "nie udawaj wywołania narzędzia" in text
