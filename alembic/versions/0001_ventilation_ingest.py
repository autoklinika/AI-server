"""Create ventilation telemetry ingestion tables.

Revision ID: 0001_ventilation_ingest
Revises:
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_ventilation_ingest"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ventilation_ingest_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("batch_id", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("source_id", "batch_id", name="uq_vent_batch_source_batch"),
    )
    op.create_table(
        "ventilation_telemetry_raw",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "batch_record_id",
            sa.Integer(),
            sa.ForeignKey("ventilation_ingest_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("sample_id", sa.String(length=160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "sample_id", name="uq_vent_sample_source_sample"),
    )
    op.create_index(
        "ix_vent_raw_source_captured",
        "ventilation_telemetry_raw",
        ["source_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vent_raw_source_captured", table_name="ventilation_telemetry_raw")
    op.drop_table("ventilation_telemetry_raw")
    op.drop_table("ventilation_ingest_batches")
