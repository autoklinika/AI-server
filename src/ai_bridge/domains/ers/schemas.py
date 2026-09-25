from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErsContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=500)
    actor_id: str = Field(min_length=1, max_length=160)
    legacy_case_code: str | None = Field(default=None, min_length=1, max_length=160)
    metadata: dict = Field(default_factory=dict)


class CasePatchRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    work_state: Literal[
        "intake",
        "diagnosing",
        "awaiting_measurement",
        "awaiting_parts",
        "repairing",
        "verifying",
        "none",
    ] | None = None
    metadata: dict | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.title is None and self.work_state is None and self.metadata is None:
            raise ValueError("PATCH requires at least one change")
        return self


class CaseTransitionRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    to_status: Literal["draft", "open", "resolved", "closed", "cancelled"]
    payload: dict = Field(default_factory=dict)


class AssetCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    asset_kind: Literal["vehicle", "machine", "bench", "other"]
    role: str = Field(min_length=1, max_length=64)
    manufacturer: str | None = Field(default=None, max_length=160)
    model: str | None = Field(default=None, max_length=160)
    vin: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=160)
    production_date: date | None = None
    engine_identity: dict = Field(default_factory=dict)
    provenance_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)


class EcuCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
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
    provenance_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)


class SymptomCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=10000)
    operating_context: dict = Field(default_factory=dict)
    provenance_id: UUID | None = None


class DtcCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    protocol: str = Field(min_length=1, max_length=32)
    ecu_id: UUID | None = None
    code: str | None = Field(default=None, max_length=64)
    spn: int | None = Field(default=None, ge=0)
    fmi: int | None = Field(default=None, ge=0)
    occurrence_count: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=32)
    raw_text: str | None = Field(default=None, max_length=10000)
    freeze_frame: dict = Field(default_factory=dict)
    provenance_id: UUID | None = None

    @model_validator(mode="after")
    def require_code(self):
        if self.code is None and self.spn is None:
            raise ValueError("code or spn is required")
        if self.fmi is not None and self.spn is None:
            raise ValueError("fmi requires spn")
        return self


class MeasurementCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    measurement_type: str = Field(min_length=1, max_length=96)
    ecu_id: UUID | None = None
    channel: str | None = Field(default=None, max_length=160)
    value_numeric: float | None = None
    value_text: str | None = None
    value_json: dict | None = None
    unit: str | None = Field(default=None, max_length=64)
    operating_context: dict = Field(default_factory=dict)
    method: str | None = Field(default=None, max_length=160)
    tool_ref: str | None = Field(default=None, max_length=160)
    provenance_id: UUID | None = None

    @model_validator(mode="after")
    def exactly_one_value(self):
        count = sum(
            value is not None
            for value in (self.value_numeric, self.value_text, self.value_json)
        )
        if count != 1:
            raise ValueError("exactly one measurement value is required")
        return self


class DiagnosticStepCreateRequest(ErsContract):
    schema_version: Literal[1] = 1
    actor_id: str = Field(min_length=1, max_length=160)
    step_type: str = Field(min_length=1, max_length=64)
    observation: str | None = None
    hypothesis_text: str | None = None
    test: str | None = None
    result: str | None = None
    next_step: str | None = None
    status: str | None = Field(default=None, max_length=32)
    provenance_id: UUID | None = None
