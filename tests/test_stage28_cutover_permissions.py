from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools/cutover_hermes_foto_modern_stage28.sh"


def test_cutover_does_not_pycompile_root_owned_usr_local_files():
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"$HERMES_PYTHON" -m py_compile "$DISPATCH_DST"' not in text
    assert '"$HERMES_PYTHON" -m py_compile "$COMPILER_DST"' not in text
    assert 'compile(path.read_text(encoding="utf-8"), str(path), "exec")' in text
    assert "without trying to create __pycache__ in /usr/local" in text
