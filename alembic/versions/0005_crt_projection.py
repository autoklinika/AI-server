"""Stage M immutable CRT projection metadata (no capture bytes)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_crt_projection"
down_revision = "0004_ers_core_persistence"
branch_labels = None
depends_on = None


def audit():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)]


def reference(name, table):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(table + ".id"), nullable=False)


def string(name, size):
    return sa.Column(name, sa.String(size), nullable=False)


def upgrade():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table("crt_projects", *audit(), string("external_id", 160), sa.UniqueConstraint("external_id"))
    op.create_table("crt_sessions", *audit(), reference("project_id", "crt_projects"),
        string("external_id", 160), sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("manifest_version", sa.Integer(), nullable=False), string("manifest_hash", 64),
        string("source_uri", 2048), sa.Column("manifest", json_type, nullable=False),
        sa.UniqueConstraint("project_id", "external_id", "manifest_hash"),
        sa.UniqueConstraint("project_id", "external_id", "manifest_version"),
        sa.CheckConstraint("schema_version = 1"), sa.CheckConstraint("manifest_version >= 1"))
    op.create_index("ix_crt_sessions_external_id", "crt_sessions", ["external_id"])
    op.create_table("crt_session_artifacts", *audit(), reference("session_id", "crt_sessions"),
        string("external_id", 160), string("source_uri", 2048), string("sha256", 64),
        sa.Column("byte_size", sa.BigInteger(), nullable=False), string("media_type", 160), string("role", 160),
        sa.UniqueConstraint("session_id", "external_id"), sa.CheckConstraint("byte_size >= 0"))
    op.create_table("crt_ers_links", *audit(), reference("session_id", "crt_sessions"),
        reference("case_id", "ers_cases"), string("role", 160), string("actor_id", 160),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "case_id", "role"))
    op.create_table("crt_ai_findings", *audit(), reference("session_id", "crt_sessions"),
        string("provider", 160), string("model", 160), string("context_hash", 64), string("status", 24),
        sa.Column("payload", json_type, nullable=False), sa.CheckConstraint("status IN ('suggested','to_review')"))
    op.create_index("ix_crt_ai_findings_session_id", "crt_ai_findings", ["session_id"])


def downgrade():
    # Destructive to projections only: require a verified Stage M backup first.
    for table in ("crt_ai_findings", "crt_ers_links", "crt_session_artifacts", "crt_sessions", "crt_projects"):
        op.drop_table(table)
