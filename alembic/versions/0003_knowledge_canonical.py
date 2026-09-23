"""Create canonical Knowledge Service persistence tables.

Revision ID: 0003_knowledge_canonical
Revises: 0002_ventilation_analysis
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_knowledge_canonical"
down_revision = "0002_ventilation_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", sa.String(length=80), primary_key=True),
        sa.Column("domain", sa.String(length=128), nullable=False),
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("acl_policy_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(length=80), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(length=80),
            sa.ForeignKey("knowledge_sources.source_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("acl_policy_id", sa.String(length=128), nullable=True),
        sa.Column("current_version_id", sa.String(length=80), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_id", "uri", name="uq_knowledge_document_source_uri"
        ),
    )
    op.create_index(
        "ix_knowledge_document_source", "knowledge_documents", ["source_id"]
    )

    op.create_table(
        "knowledge_document_versions",
        sa.Column("version_id", sa.String(length=80), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=80),
            sa.ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.String(length=160), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "document_id",
            "content_sha256",
            name="uq_knowledge_version_document_hash",
        ),
    )
    op.create_index(
        "ix_knowledge_version_document",
        "knowledge_document_versions",
        ["document_id"],
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(length=80), primary_key=True),
        sa.Column(
            "version_id",
            sa.String(length=80),
            sa.ForeignKey("knowledge_document_versions.version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_profile", sa.String(length=96), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "version_id",
            "chunk_profile",
            "ordinal",
            name="uq_knowledge_chunk_version_profile_ordinal",
        ),
    )
    op.create_index(
        "ix_knowledge_chunk_version_profile",
        "knowledge_chunks",
        ["version_id", "chunk_profile"],
    )

    op.create_table(
        "knowledge_index_jobs",
        sa.Column("job_id", sa.String(length=80), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=80),
            sa.ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.String(length=80),
            sa.ForeignKey("knowledge_document_versions.version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_profile", sa.String(length=96), nullable=False),
        sa.Column("index_profile", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "version_id",
            "chunk_profile",
            "index_profile",
            name="uq_knowledge_index_job_version_profiles",
        ),
    )
    op.create_index(
        "ix_knowledge_index_job_state_created",
        "knowledge_index_jobs",
        ["state", "created_at"],
    )
    op.create_index(
        "ix_knowledge_index_job_document",
        "knowledge_index_jobs",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_index_job_document", table_name="knowledge_index_jobs")
    op.drop_index(
        "ix_knowledge_index_job_state_created", table_name="knowledge_index_jobs"
    )
    op.drop_table("knowledge_index_jobs")
    op.drop_index(
        "ix_knowledge_chunk_version_profile", table_name="knowledge_chunks"
    )
    op.drop_table("knowledge_chunks")
    op.drop_index(
        "ix_knowledge_version_document", table_name="knowledge_document_versions"
    )
    op.drop_table("knowledge_document_versions")
    op.drop_index("ix_knowledge_document_source", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_sources")
