from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_bridge.storage.base import Base


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
UUID_TYPE = Uuid(as_uuid=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ErsCaseCounterModel(Base):
    __tablename__ = "ers_case_counters"

    counter_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ErsCaseModel(Base):
    __tablename__ = "ers_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','open','resolved','closed','cancelled')",
            name="ck_ers_cases_status",
        ),
        CheckConstraint(
            "work_state IS NULL OR work_state IN "
            "('intake','diagnosing','awaiting_measurement','awaiting_parts',"
            "'repairing','verifying','none')",
            name="ck_ers_cases_work_state",
        ),
        CheckConstraint("row_version >= 1", name="ck_ers_cases_row_version"),
        Index("ix_ers_cases_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    legacy_case_code: Mapped[str | None] = mapped_column(
        String(160), unique=True, nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    work_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(160), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsCaseEventModel(Base):
    __tablename__ = "ers_case_events"
    __table_args__ = (
        UniqueConstraint("case_id", "event_seq", name="uq_ers_case_event_seq"),
        Index("ix_ers_case_events_case_time", "case_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(24))
    new_status: Mapped[str | None] = mapped_column(String(24))
    previous_work_state: Mapped[str | None] = mapped_column(String(32))
    new_work_state: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(160))
    correlation_id: Mapped[str | None] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    payload: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)


class ErsProvenanceRecordModel(Base):
    __tablename__ = "ers_provenance_records"
    __table_args__ = (
        Index("ix_ers_provenance_origin", "origin_type", "acquired_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    origin_type: Mapped[str] = mapped_column(String(64), nullable=False)
    origin_uri: Mapped[str | None] = mapped_column(Text)
    origin_ref: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String(160))
    acquisition_method: Mapped[str | None] = mapped_column(String(128))
    tool: Mapped[str | None] = mapped_column(String(160))
    tool_version: Mapped[str | None] = mapped_column(String(128))
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    request_id: Mapped[str | None] = mapped_column(String(160))
    correlation_id: Mapped[str | None] = mapped_column(String(160))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsProvenanceEdgeModel(Base):
    __tablename__ = "ers_provenance_edges"
    __table_args__ = (
        CheckConstraint(
            "relation_type IN "
            "('derived_from','copied_from','measured_from','extracted_from','supersedes')",
            name="ck_ers_provenance_edge_relation",
        ),
        UniqueConstraint(
            "from_provenance_id", "to_provenance_id", "relation_type",
            name="uq_ers_provenance_edge",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    from_provenance_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("ers_provenance_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_provenance_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("ers_provenance_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErsAssetModel(Base):
    __tablename__ = "ers_assets"
    __table_args__ = (
        CheckConstraint(
            "asset_kind IN ('vehicle','machine','bench','other')",
            name="ck_ers_assets_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    asset_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsAssetRevisionModel(Base):
    __tablename__ = "ers_asset_revisions"
    __table_args__ = (
        Index("ix_ers_asset_revisions_asset_time", "asset_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_assets.id", ondelete="CASCADE"), nullable=False
    )
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    vin: Mapped[str | None] = mapped_column(String(64))
    serial_number: Mapped[str | None] = mapped_column(String(160))
    production_date: Mapped[date | None] = mapped_column(Date)
    engine_identity: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsCaseAssetModel(Base):
    __tablename__ = "ers_case_assets"
    __table_args__ = (
        UniqueConstraint("case_id", "asset_id", "role", name="uq_ers_case_asset_role"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_assets.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErsEcuModel(Base):
    __tablename__ = "ers_ecus"

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsCaseEcuModel(Base):
    __tablename__ = "ers_case_ecus"
    __table_args__ = (
        CheckConstraint(
            "role IN ('original','donor','replacement','target','reference')",
            name="ck_ers_case_ecu_role",
        ),
        UniqueConstraint("case_id", "ecu_id", "role", name="uq_ers_case_ecu_role"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    ecu_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_ecus.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErsEcuIdentityObservationModel(Base):
    __tablename__ = "ers_ecu_identity_observations"
    __table_args__ = (
        Index("ix_ers_ecu_identity_ecu_time", "ecu_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    ecu_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_ecus.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="SET NULL")
    )
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    family: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    hardware_number: Mapped[str | None] = mapped_column(String(160))
    hardware_revision: Mapped[str | None] = mapped_column(String(160))
    assembly_part_number: Mapped[str | None] = mapped_column(String(160))
    serial_number: Mapped[str | None] = mapped_column(String(160))
    mcu_marking: Mapped[str | None] = mapped_column(String(160))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsEcuSoftwareObservationModel(Base):
    __tablename__ = "ers_ecu_software_observations"
    __table_args__ = (
        Index("ix_ers_ecu_software_ecu_time", "ecu_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    ecu_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_ecus.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="SET NULL")
    )
    software_number: Mapped[str | None] = mapped_column(String(160))
    calibration_number: Mapped[str | None] = mapped_column(String(160))
    boot_id: Mapped[str | None] = mapped_column(String(160))
    coding_id: Mapped[str | None] = mapped_column(String(160))
    dataset_id: Mapped[str | None] = mapped_column(String(160))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsSymptomModel(Base):
    __tablename__ = "ers_symptoms"
    __table_args__ = (Index("ix_ers_symptoms_case_time", "case_id", "observed_at"),)

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    operating_context: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )


class ErsDtcModel(Base):
    __tablename__ = "ers_dtcs"
    __table_args__ = (Index("ix_ers_dtcs_case_time", "case_id", "observed_at"),)

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    ecu_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_ecus.id", ondelete="SET NULL")
    )
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64))
    spn: Mapped[int | None] = mapped_column(Integer)
    fmi: Mapped[int | None] = mapped_column(Integer)
    occurrence_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(32))
    raw_text: Mapped[str | None] = mapped_column(Text)
    freeze_frame: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )


class ErsMeasurementModel(Base):
    __tablename__ = "ers_measurements"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN value_numeric IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_json IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_ers_measurements_one_value",
        ),
        Index("ix_ers_measurements_case_time", "case_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    ecu_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_ecus.id", ondelete="SET NULL")
    )
    measurement_type: Mapped[str] = mapped_column(String(96), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(160))
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    unit: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    operating_context: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    method: Mapped[str | None] = mapped_column(String(160))
    tool_ref: Mapped[str | None] = mapped_column(String(160))
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )


class ErsDiagnosticStepModel(Base):
    __tablename__ = "ers_diagnostic_steps"
    __table_args__ = (
        UniqueConstraint("case_id", "step_seq", name="uq_ers_diagnostic_step_seq"),
        Index("ix_ers_diagnostic_steps_case_time", "case_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    step_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False)
    observation: Mapped[str | None] = mapped_column(Text)
    hypothesis_text: Mapped[str | None] = mapped_column(Text)
    test: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    next_step: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )


class ErsHypothesisModel(Base):
    __tablename__ = "ers_hypotheses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','supported','contradicted','rejected','confirmed')",
            name="ck_ers_hypotheses_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ers_hypotheses_confidence",
        ),
        Index("ix_ers_hypotheses_case_created", "case_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )


class ErsRepairActionModel(Base):
    __tablename__ = "ers_repair_actions"
    __table_args__ = (Index("ix_ers_repair_actions_case", "case_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_text: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(String(160))
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErsCaseResultModel(Base):
    __tablename__ = "ers_case_results"
    __table_args__ = (Index("ix_ers_case_results_case", "case_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    root_cause_statement: Mapped[str | None] = mapped_column(Text)
    verification: Mapped[str | None] = mapped_column(Text)
    confirmation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_result_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_case_results.id", ondelete="SET NULL")
    )
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErsArtifactModel(Base):
    __tablename__ = "ers_artifacts"
    __table_args__ = (
        CheckConstraint(
            "artifact_kind IN "
            "('photo','pdf','binary','log','can_capture','scope_trace',"
            "'measurement_export','text','other')",
            name="ck_ers_artifacts_kind",
        ),
        Index("ix_ers_artifacts_case_kind", "case_id", "artifact_kind"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    ecu_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_ecus.id", ondelete="SET NULL")
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_assets.id", ondelete="SET NULL")
    )
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(String(64))
    original_filename: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsArtifactVersionModel(Base):
    __tablename__ = "ers_artifact_versions"
    __table_args__ = (
        CheckConstraint(
            "availability IN ('available','missing_original','quarantined')",
            name="ck_ers_artifact_versions_availability",
        ),
        CheckConstraint("byte_size >= 0", name="ck_ers_artifact_versions_byte_size"),
        CheckConstraint("version_no >= 1", name="ck_ers_artifact_versions_version_no"),
        CheckConstraint(
            "availability != 'available' OR object_sha256 IS NOT NULL",
            name="ck_ers_artifact_versions_available_hash",
        ),
        UniqueConstraint(
            "artifact_id", "version_no", name="uq_ers_artifact_version_number"
        ),
        Index("ix_ers_artifact_versions_sha", "object_sha256"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    object_sha256: Mapped[str | None] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(160))
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    parent_artifact_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_artifact_versions.id", ondelete="SET NULL")
    )
    derivation_type: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict
    )


class ErsEvidenceModel(Base):
    __tablename__ = "ers_evidence"
    __table_args__ = (
        CheckConstraint(
            "authority IN "
            "('workshop_observation','manufacturer_documentation','measured_data',"
            "'derived_analysis','user_statement','knowledge_retrieval','ai_inference')",
            name="ck_ers_evidence_authority",
        ),
        Index("ix_ers_evidence_case_created", "case_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_cases.id", ondelete="CASCADE"), nullable=False
    )
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str | None] = mapped_column(Text)
    artifact_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_artifact_versions.id", ondelete="SET NULL")
    )
    measurement_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_measurements.id", ondelete="SET NULL")
    )
    diagnostic_step_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_diagnostic_steps.id", ondelete="SET NULL")
    )
    knowledge_document_id: Mapped[str | None] = mapped_column(String(80))
    knowledge_version_id: Mapped[str | None] = mapped_column(String(80))
    knowledge_chunk_id: Mapped[str | None] = mapped_column(String(80))
    locator: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    provenance_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("ers_provenance_records.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ErsHypothesisEvidenceModel(Base):
    __tablename__ = "ers_hypothesis_evidence"
    __table_args__ = (
        CheckConstraint(
            "polarity IN ('support','contradict','context')",
            name="ck_ers_hypothesis_evidence_polarity",
        ),
        UniqueConstraint(
            "hypothesis_id", "evidence_id", "polarity",
            name="uq_ers_hypothesis_evidence",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid4)
    hypothesis_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_hypotheses.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("ers_evidence.id", ondelete="CASCADE"), nullable=False
    )
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
