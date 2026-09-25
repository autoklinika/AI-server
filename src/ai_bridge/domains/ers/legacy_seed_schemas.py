from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedAsset(SeedModel):
    asset_kind: Literal["vehicle", "machine", "bench", "other"]
    role: str = Field(min_length=1, max_length=64)
    manufacturer: str | None = Field(default=None, max_length=160)
    model: str | None = Field(default=None, max_length=160)
    serial_number: str | None = Field(default=None, max_length=160)
    engine_identity: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class SeedEcu(SeedModel):
    role: Literal["original", "donor", "replacement", "target", "reference"]
    manufacturer: str | None = Field(default=None, max_length=160)
    family: str | None = Field(default=None, max_length=160)
    model: str | None = Field(default=None, max_length=160)
    hardware_number: str | None = Field(default=None, max_length=160)
    hardware_revision: str | None = Field(default=None, max_length=160)
    assembly_part_number: str | None = Field(default=None, max_length=160)
    serial_number: str | None = Field(default=None, max_length=160)
    mcu_marking: str | None = Field(default=None, max_length=160)

    software_number: str | None = Field(default=None, max_length=160)
    calibration_number: str | None = Field(default=None, max_length=160)
    boot_id: str | None = Field(default=None, max_length=160)
    coding_id: str | None = Field(default=None, max_length=160)
    dataset_id: str | None = Field(default=None, max_length=160)
    metadata: dict = Field(default_factory=dict)


class SeedSymptom(SeedModel):
    description: str = Field(min_length=1, max_length=10000)
    operating_context: dict = Field(default_factory=dict)


class SeedDtc(SeedModel):
    protocol: str = Field(min_length=1, max_length=32)
    ecu_role: str | None = Field(default=None, max_length=32)
    code: str | None = Field(default=None, max_length=64)
    spn: int | None = Field(default=None, ge=0)
    fmi: int | None = Field(default=None, ge=0)
    occurrence_count: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=32)
    raw_text: str | None = Field(default=None, max_length=10000)
    freeze_frame: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_code(self):
        if self.code is None and self.spn is None:
            raise ValueError("DTC requires code or spn")
        if self.fmi is not None and self.spn is None:
            raise ValueError("fmi requires spn")
        return self

class SeedDiagnosticStep(SeedModel):
    step_type: str = Field(min_length=1, max_length=64)
    observation: str | None = None
    hypothesis_text: str | None = None
    test: str | None = None
    result: str | None = None
    next_step: str | None = None
    status: str | None = Field(default=None, max_length=32)


class SeedRepairAction(SeedModel):
    action: str = Field(min_length=1)
    status: str = Field(min_length=1, max_length=32)
    result_text: str | None = None


class SeedResult(SeedModel):
    outcome: str = Field(min_length=1, max_length=64)
    root_cause_statement: str | None = None
    verification: str | None = None
    confirmation_status: str = Field(min_length=1, max_length=32)


class SeedArtifact(SeedModel):
    artifact_kind: Literal[
        "photo", "pdf", "binary", "log", "can_capture",
        "scope_trace", "measurement_export", "text", "other"
    ]
    role: str = Field(min_length=1, max_length=64)
    source_kind: Literal["repo_file", "local_original"]
    path: str = Field(min_length=1)
    media_type: str | None = Field(default=None, max_length=160)
    ecu_role: str | None = Field(default=None, max_length=32)
    byte_size: int | None = Field(default=None, ge=0)
    sha256: str | None = None

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_kind == "local_original":
            if self.byte_size is None or self.sha256 is None:
                raise ValueError("local_original requires byte_size and sha256")
            if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
                raise ValueError("sha256 must be lowercase hex")
        return self

class LegacyCaseSeed(SeedModel):
    schema_version: Literal[1]
    legacy_case_code: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=500)
    final_status: Literal["draft", "open", "resolved", "closed", "cancelled"]
    final_work_state: Literal[
        "intake", "diagnosing", "awaiting_measurement", "awaiting_parts",
        "repairing", "verifying", "none"
    ] | None = None
    case_metadata: dict = Field(default_factory=dict)
    asset: SeedAsset | None = None
    ecus: list[SeedEcu] = Field(default_factory=list)
    symptoms: list[SeedSymptom] = Field(default_factory=list)
    dtcs: list[SeedDtc] = Field(default_factory=list)
    diagnostic_steps: list[SeedDiagnosticStep] = Field(default_factory=list)
    repair_actions: list[SeedRepairAction] = Field(default_factory=list)
    results: list[SeedResult] = Field(default_factory=list)
    artifacts: list[SeedArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_roles(self):
        roles = [ecu.role for ecu in self.ecus]
        if len(roles) != len(set(roles)):
            raise ValueError("ECU roles must be unique in seed v1")
        known = set(roles)
        for dtc in self.dtcs:
            if dtc.ecu_role is not None and dtc.ecu_role not in known:
                raise ValueError(f"unknown dtc ecu_role: {dtc.ecu_role}")
        for artifact in self.artifacts:
            if artifact.ecu_role is not None and artifact.ecu_role not in known:
                raise ValueError(f"unknown artifact ecu_role: {artifact.ecu_role}")
        return self
