from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_gateway_lock_includes_postgres_driver_for_stage_j_knowledge() -> None:
    lines = (
        ROOT / "deploy/stage-a/locks/ai-gateway.requirements.txt"
    ).read_text().splitlines()
    assert "psycopg==3.3.4" in lines
    assert "psycopg-binary==3.3.4" in lines


def test_stage_j_release_build_verifies_gateway_postgres_import() -> None:
    text = (ROOT / "deploy/runtime/build_release.sh").read_text()
    marker = 'print("KNOWLEDGE SERVICE: PASS")'
    end = text.index(marker)
    knowledge_block = text[max(0, end - 500):end + len(marker)]
    assert "import psycopg" in knowledge_block
    assert marker in knowledge_block
