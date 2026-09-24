"""Create ERS core persistence tables.

Revision ID: 0004_ers_core_persistence
Revises: 0003_knowledge_canonical
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_ers_core_persistence"
down_revision = "0003_knowledge_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ers_assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('asset_kind', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.CheckConstraint("asset_kind IN ('vehicle','machine','bench','other')", name='ck_ers_assets_kind'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ers_case_counters',
    sa.Column('counter_name', sa.String(length=32), nullable=False),
    sa.Column('next_value', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('counter_name')
    )
    op.execute(sa.text("INSERT INTO ers_case_counters (counter_name, next_value) VALUES ('case', 1)"))
    op.create_table('ers_cases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_code', sa.String(length=32), nullable=False),
    sa.Column('legacy_case_code', sa.String(length=160), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('work_state', sa.String(length=32), nullable=True),
    sa.Column('row_version', sa.BigInteger(), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=160), nullable=False),
    sa.Column('updated_by', sa.String(length=160), nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.CheckConstraint("status IN ('draft','open','resolved','closed','cancelled')", name='ck_ers_cases_status'),
    sa.CheckConstraint("work_state IS NULL OR work_state IN ('intake','diagnosing','awaiting_measurement','awaiting_parts','repairing','verifying','none')", name='ck_ers_cases_work_state'),
    sa.CheckConstraint('row_version >= 1', name='ck_ers_cases_row_version'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_code'),
    sa.UniqueConstraint('legacy_case_code')
    )
    op.create_index('ix_ers_cases_status_updated', 'ers_cases', ['status', 'updated_at'], unique=False)
    op.create_table('ers_ecus',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ers_provenance_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('origin_type', sa.String(length=64), nullable=False),
    sa.Column('origin_uri', sa.Text(), nullable=True),
    sa.Column('origin_ref', sa.Text(), nullable=True),
    sa.Column('actor_id', sa.String(length=160), nullable=True),
    sa.Column('acquisition_method', sa.String(length=128), nullable=True),
    sa.Column('tool', sa.String(length=160), nullable=True),
    sa.Column('tool_version', sa.String(length=128), nullable=True),
    sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('request_id', sa.String(length=160), nullable=True),
    sa.Column('correlation_id', sa.String(length=160), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_provenance_origin', 'ers_provenance_records', ['origin_type', 'acquired_at'], unique=False)
    op.create_table('ers_artifacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('ecu_id', sa.Uuid(), nullable=True),
    sa.Column('asset_id', sa.Uuid(), nullable=True),
    sa.Column('artifact_kind', sa.String(length=32), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('role', sa.String(length=64), nullable=True),
    sa.Column('original_filename', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=160), nullable=False),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.CheckConstraint("artifact_kind IN ('photo','pdf','binary','log','can_capture','scope_trace','measurement_export','text','other')", name='ck_ers_artifacts_kind'),
    sa.ForeignKeyConstraint(['asset_id'], ['ers_assets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ecu_id'], ['ers_ecus.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_artifacts_case_kind', 'ers_artifacts', ['case_id', 'artifact_kind'], unique=False)
    op.create_table('ers_asset_revisions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('manufacturer', sa.String(length=160), nullable=True),
    sa.Column('model', sa.String(length=160), nullable=True),
    sa.Column('vin', sa.String(length=64), nullable=True),
    sa.Column('serial_number', sa.String(length=160), nullable=True),
    sa.Column('production_date', sa.Date(), nullable=True),
    sa.Column('engine_identity', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['ers_assets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_asset_revisions_asset_time', 'ers_asset_revisions', ['asset_id', 'observed_at'], unique=False)
    op.create_table('ers_case_assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['ers_assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'asset_id', 'role', name='uq_ers_case_asset_role')
    )
    op.create_table('ers_case_ecus',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('ecu_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('original','donor','replacement','target','reference')", name='ck_ers_case_ecu_role'),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ecu_id'], ['ers_ecus.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'ecu_id', 'role', name='uq_ers_case_ecu_role')
    )
    op.create_table('ers_case_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('event_seq', sa.BigInteger(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('previous_status', sa.String(length=24), nullable=True),
    sa.Column('new_status', sa.String(length=24), nullable=True),
    sa.Column('previous_work_state', sa.String(length=32), nullable=True),
    sa.Column('new_work_state', sa.String(length=32), nullable=True),
    sa.Column('actor_id', sa.String(length=160), nullable=False),
    sa.Column('request_id', sa.String(length=160), nullable=True),
    sa.Column('correlation_id', sa.String(length=160), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'event_seq', name='uq_ers_case_event_seq')
    )
    op.create_index('ix_ers_case_events_case_time', 'ers_case_events', ['case_id', 'occurred_at'], unique=False)
    op.create_table('ers_case_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('outcome', sa.String(length=64), nullable=False),
    sa.Column('root_cause_statement', sa.Text(), nullable=True),
    sa.Column('verification', sa.Text(), nullable=True),
    sa.Column('confirmation_status', sa.String(length=32), nullable=False),
    sa.Column('supersedes_result_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.String(length=160), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supersedes_result_id'], ['ers_case_results.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_case_results_case', 'ers_case_results', ['case_id', 'created_at'], unique=False)
    op.create_table('ers_diagnostic_steps',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('step_seq', sa.BigInteger(), nullable=False),
    sa.Column('step_type', sa.String(length=64), nullable=False),
    sa.Column('observation', sa.Text(), nullable=True),
    sa.Column('hypothesis_text', sa.Text(), nullable=True),
    sa.Column('test', sa.Text(), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('next_step', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'step_seq', name='uq_ers_diagnostic_step_seq')
    )
    op.create_index('ix_ers_diagnostic_steps_case_time', 'ers_diagnostic_steps', ['case_id', 'occurred_at'], unique=False)
    op.create_table('ers_dtcs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('ecu_id', sa.Uuid(), nullable=True),
    sa.Column('protocol', sa.String(length=32), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=True),
    sa.Column('spn', sa.Integer(), nullable=True),
    sa.Column('fmi', sa.Integer(), nullable=True),
    sa.Column('occurrence_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('freeze_frame', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ecu_id'], ['ers_ecus.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_dtcs_case_time', 'ers_dtcs', ['case_id', 'observed_at'], unique=False)
    op.create_table('ers_ecu_identity_observations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('ecu_id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=True),
    sa.Column('manufacturer', sa.String(length=160), nullable=True),
    sa.Column('family', sa.String(length=160), nullable=True),
    sa.Column('model', sa.String(length=160), nullable=True),
    sa.Column('hardware_number', sa.String(length=160), nullable=True),
    sa.Column('hardware_revision', sa.String(length=160), nullable=True),
    sa.Column('assembly_part_number', sa.String(length=160), nullable=True),
    sa.Column('serial_number', sa.String(length=160), nullable=True),
    sa.Column('mcu_marking', sa.String(length=160), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ecu_id'], ['ers_ecus.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_ecu_identity_ecu_time', 'ers_ecu_identity_observations', ['ecu_id', 'observed_at'], unique=False)
    op.create_table('ers_ecu_software_observations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('ecu_id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=True),
    sa.Column('software_number', sa.String(length=160), nullable=True),
    sa.Column('calibration_number', sa.String(length=160), nullable=True),
    sa.Column('boot_id', sa.String(length=160), nullable=True),
    sa.Column('coding_id', sa.String(length=160), nullable=True),
    sa.Column('dataset_id', sa.String(length=160), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ecu_id'], ['ers_ecus.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_ecu_software_ecu_time', 'ers_ecu_software_observations', ['ecu_id', 'observed_at'], unique=False)
    op.create_table('ers_hypotheses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=160), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("status IN ('proposed','supported','contradicted','rejected','confirmed')", name='ck_ers_hypotheses_status'),
    sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 1)', name='ck_ers_hypotheses_confidence'),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_hypotheses_case_created', 'ers_hypotheses', ['case_id', 'created_at'], unique=False)
    op.create_table('ers_measurements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('ecu_id', sa.Uuid(), nullable=True),
    sa.Column('measurement_type', sa.String(length=96), nullable=False),
    sa.Column('channel', sa.String(length=160), nullable=True),
    sa.Column('value_numeric', sa.Float(), nullable=True),
    sa.Column('value_text', sa.Text(), nullable=True),
    sa.Column('value_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('unit', sa.String(length=64), nullable=True),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('operating_context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('method', sa.String(length=160), nullable=True),
    sa.Column('tool_ref', sa.String(length=160), nullable=True),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint('(CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_json IS NOT NULL THEN 1 ELSE 0 END) = 1', name='ck_ers_measurements_one_value'),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ecu_id'], ['ers_ecus.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_measurements_case_time', 'ers_measurements', ['case_id', 'captured_at'], unique=False)
    op.create_table('ers_provenance_edges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('from_provenance_id', sa.Uuid(), nullable=False),
    sa.Column('to_provenance_id', sa.Uuid(), nullable=False),
    sa.Column('relation_type', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("relation_type IN ('derived_from','copied_from','measured_from','extracted_from','supersedes')", name='ck_ers_provenance_edge_relation'),
    sa.ForeignKeyConstraint(['from_provenance_id'], ['ers_provenance_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_provenance_id'], ['ers_provenance_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('from_provenance_id', 'to_provenance_id', 'relation_type', name='uq_ers_provenance_edge')
    )
    op.create_table('ers_repair_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('planned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('performed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('result_text', sa.Text(), nullable=True),
    sa.Column('actor_id', sa.String(length=160), nullable=True),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_repair_actions_case', 'ers_repair_actions', ['case_id', 'created_at'], unique=False)
    op.create_table('ers_symptoms',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('operating_context', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_symptoms_case_time', 'ers_symptoms', ['case_id', 'observed_at'], unique=False)
    op.create_table('ers_artifact_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('artifact_id', sa.Uuid(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('object_sha256', sa.String(length=64), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('media_type', sa.String(length=160), nullable=True),
    sa.Column('availability', sa.String(length=32), nullable=False),
    sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('parent_artifact_version_id', sa.Uuid(), nullable=True),
    sa.Column('derivation_type', sa.String(length=64), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.CheckConstraint("availability IN ('available','missing_original','quarantined')", name='ck_ers_artifact_versions_availability'),
    sa.CheckConstraint('byte_size >= 0', name='ck_ers_artifact_versions_byte_size'),
    sa.CheckConstraint("availability != 'available' OR object_sha256 IS NOT NULL", name='ck_ers_artifact_versions_available_hash'),
    sa.CheckConstraint('version_no >= 1', name='ck_ers_artifact_versions_version_no'),
    sa.ForeignKeyConstraint(['artifact_id'], ['ers_artifacts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_artifact_version_id'], ['ers_artifact_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('artifact_id', 'version_no', name='uq_ers_artifact_version_number')
    )
    op.create_index('ix_ers_artifact_versions_sha', 'ers_artifact_versions', ['object_sha256'], unique=False)
    op.create_table('ers_evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('authority', sa.String(length=64), nullable=False),
    sa.Column('evidence_type', sa.String(length=64), nullable=False),
    sa.Column('statement', sa.Text(), nullable=True),
    sa.Column('artifact_version_id', sa.Uuid(), nullable=True),
    sa.Column('measurement_id', sa.Uuid(), nullable=True),
    sa.Column('diagnostic_step_id', sa.Uuid(), nullable=True),
    sa.Column('knowledge_document_id', sa.String(length=80), nullable=True),
    sa.Column('knowledge_version_id', sa.String(length=80), nullable=True),
    sa.Column('knowledge_chunk_id', sa.String(length=80), nullable=True),
    sa.Column('locator', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('provenance_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("authority IN ('workshop_observation','manufacturer_documentation','measured_data','derived_analysis','user_statement','knowledge_retrieval','ai_inference')", name='ck_ers_evidence_authority'),
    sa.ForeignKeyConstraint(['artifact_version_id'], ['ers_artifact_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['case_id'], ['ers_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['diagnostic_step_id'], ['ers_diagnostic_steps.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['measurement_id'], ['ers_measurements.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['provenance_id'], ['ers_provenance_records.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ers_evidence_case_created', 'ers_evidence', ['case_id', 'created_at'], unique=False)
    op.create_table('ers_hypothesis_evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hypothesis_id', sa.Uuid(), nullable=False),
    sa.Column('evidence_id', sa.Uuid(), nullable=False),
    sa.Column('polarity', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("polarity IN ('support','contradict','context')", name='ck_ers_hypothesis_evidence_polarity'),
    sa.ForeignKeyConstraint(['evidence_id'], ['ers_evidence.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['hypothesis_id'], ['ers_hypotheses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hypothesis_id', 'evidence_id', 'polarity', name='uq_ers_hypothesis_evidence')
    )


def downgrade() -> None:
    op.drop_table('ers_hypothesis_evidence')
    op.drop_index('ix_ers_evidence_case_created', table_name='ers_evidence')
    op.drop_table('ers_evidence')
    op.drop_index('ix_ers_artifact_versions_sha', table_name='ers_artifact_versions')
    op.drop_table('ers_artifact_versions')
    op.drop_index('ix_ers_symptoms_case_time', table_name='ers_symptoms')
    op.drop_table('ers_symptoms')
    op.drop_index('ix_ers_repair_actions_case', table_name='ers_repair_actions')
    op.drop_table('ers_repair_actions')
    op.drop_table('ers_provenance_edges')
    op.drop_index('ix_ers_measurements_case_time', table_name='ers_measurements')
    op.drop_table('ers_measurements')
    op.drop_index('ix_ers_hypotheses_case_created', table_name='ers_hypotheses')
    op.drop_table('ers_hypotheses')
    op.drop_index('ix_ers_ecu_software_ecu_time', table_name='ers_ecu_software_observations')
    op.drop_table('ers_ecu_software_observations')
    op.drop_index('ix_ers_ecu_identity_ecu_time', table_name='ers_ecu_identity_observations')
    op.drop_table('ers_ecu_identity_observations')
    op.drop_index('ix_ers_dtcs_case_time', table_name='ers_dtcs')
    op.drop_table('ers_dtcs')
    op.drop_index('ix_ers_diagnostic_steps_case_time', table_name='ers_diagnostic_steps')
    op.drop_table('ers_diagnostic_steps')
    op.drop_index('ix_ers_case_results_case', table_name='ers_case_results')
    op.drop_table('ers_case_results')
    op.drop_index('ix_ers_case_events_case_time', table_name='ers_case_events')
    op.drop_table('ers_case_events')
    op.drop_table('ers_case_ecus')
    op.drop_table('ers_case_assets')
    op.drop_index('ix_ers_asset_revisions_asset_time', table_name='ers_asset_revisions')
    op.drop_table('ers_asset_revisions')
    op.drop_index('ix_ers_artifacts_case_kind', table_name='ers_artifacts')
    op.drop_table('ers_artifacts')
    op.drop_index('ix_ers_provenance_origin', table_name='ers_provenance_records')
    op.drop_table('ers_provenance_records')
    op.drop_table('ers_ecus')
    op.drop_index('ix_ers_cases_status_updated', table_name='ers_cases')
    op.drop_table('ers_cases')
    op.drop_table('ers_case_counters')
    op.drop_table('ers_assets')
