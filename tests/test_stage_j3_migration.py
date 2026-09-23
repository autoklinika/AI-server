from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


KNOWLEDGE_TABLES = {
    "knowledge_sources",
    "knowledge_documents",
    "knowledge_document_versions",
    "knowledge_chunks",
    "knowledge_index_jobs",
}


def test_j3_migration_upgrade_and_downgrade(monkeypatch, tmp_path):
    database_path = tmp_path / "migration.sqlite"
    database_url = "sqlite+pysqlite:///" + str(database_path)
    monkeypatch.setenv("AI_BRIDGE_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert KNOWLEDGE_TABLES <= tables
    finally:
        engine.dispose()

    command.downgrade(config, "0002_ventilation_analysis")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert KNOWLEDGE_TABLES.isdisjoint(tables)
    finally:
        engine.dispose()
