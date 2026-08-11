"""Create ventilation advisory analysis table.

Revision ID: 0002_ventilation_analysis
Revises: 0001_ventilation_ingest
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_ventilation_analysis"
down_revision = "0001_ventilation_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ventilation_analysis_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("prompt_eval_count", sa.Integer(), nullable=True),
        sa.Column("eval_count", sa.Integer(), nullable=True),
        sa.Column("total_duration_ns", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("analysis_id", name="uq_vent_analysis_id"),
        sa.UniqueConstraint(
            "source_id",
            "window_start",
            "window_end",
            "model",
            "prompt_version",
            name="uq_vent_analysis_window_model_prompt",
        ),
    )
    op.create_index(
        "ix_vent_analysis_source_window_end",
        "ventilation_analysis_runs",
        ["source_id", "window_end"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vent_analysis_source_window_end",
        table_name="ventilation_analysis_runs",
    )
    op.drop_table("ventilation_analysis_runs")
