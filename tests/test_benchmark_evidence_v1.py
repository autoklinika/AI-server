from ai_bridge.benchmarks.evidence import _resolve_locator


def test_binary_locator_uses_deterministic_metadata_stub(tmp_path):
    payload = b"%PDF-1.7\n\xaa\xbb\x00binary"
    path = tmp_path / "source.pdf"
    path.write_bytes(payload)

    text = _resolve_locator("source.pdf", (tmp_path,))

    assert text is not None
    assert "[BINARY EVIDENCE NOT EMBEDDED]" in text
    assert "filename: source.pdf" in text
    assert f"byte_size: {len(payload)}" in text
    digest = text.rsplit("sha256: ", 1)[1]
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_text_locator_still_returns_markdown_section(tmp_path):
    path = tmp_path / "source.md"
    path.write_text("# A\nalpha\n\n## B\nbeta\n\n# C\ngamma\n", encoding="utf-8")

    text = _resolve_locator("source.md#B", (tmp_path,))

    assert text == "## B\nbeta"
