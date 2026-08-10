from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FanSetpoints(StrictModel):
    supply_voltage: float = Field(ge=0.0, le=10.0)
    extract_voltage: float = Field(ge=0.0, le=10.0)


class AlarmState(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    severity: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=1024)
    active_since: AwareDatetime
    last_error: str = Field(max_length=4096)
    occurrences: int = Field(ge=0)


class AirQualityReading(StrictModel):
    pm1_0_ug_m3: float | None = None
    pm2_5_ug_m3: float | None = None
    pm4_0_ug_m3: float | None = None
    pm10_0_ug_m3: float | None = None
    humidity_percent: float | None = None
    temperature_celsius: float | None = None
    voc_index: float | None = None
    nox_index: float | None = None


class SensorNodeState(StrictModel):
    slave_address: int = Field(ge=1, le=247)
    online: bool
    usable: bool
    measurement_valid: bool
    measurement_stale: bool
    sensor_present: bool
    availability_mask: int = Field(ge=0, le=0xFFFF)
    status_mask: int = Field(ge=0, le=0xFFFF)
    reading: AirQualityReading
    age_seconds: int | None = Field(default=None, ge=0)
    sensor_errors: int = Field(ge=0)
    modbus_service_errors: int = Field(ge=0)
    uptime_seconds: int = Field(ge=0)
    firmware_version: str | None = Field(default=None, max_length=64)
    map_version: int | None = Field(default=None, ge=0)
    sequence: int = Field(ge=0)
    last_success_at: AwareDatetime | None = None
    last_error: str | None = Field(default=None, max_length=4096)
    polls: int = Field(ge=0)
    successful_polls: int = Field(ge=0)
    communication_errors: int = Field(ge=0)
    consecutive_failures: int = Field(ge=0)
    invalid_measurements: int = Field(ge=0)
    stale_measurements: int = Field(ge=0)
    map_version_errors: int = Field(ge=0)


class SensorBusState(StrictModel):
    port: str = Field(min_length=1, max_length=256)
    baudrate: int = Field(gt=0)
    addresses: list[int] = Field(min_length=1)
    ready: bool
    worker_alive: bool
    worker_restarts: int = Field(ge=0)
    expected_map_version: int = Field(ge=0)
    inter_node_delay_seconds: float = Field(ge=0.0)
    poll_interval_seconds: float = Field(gt=0.0)
    last_cycle_at: AwareDatetime | None = None
    last_error: str | None = Field(default=None, max_length=4096)
    nodes: list[SensorNodeState]

    @model_validator(mode="after")
    def validate_addresses(self) -> "SensorBusState":
        if len(set(self.addresses)) != len(self.addresses):
            raise ValueError("sensor_bus.addresses must be unique")
        node_addresses = [node.slave_address for node in self.nodes]
        if len(set(node_addresses)) != len(node_addresses):
            raise ValueError("sensor_bus.nodes slave_address values must be unique")
        if any(address < 1 or address > 247 for address in self.addresses):
            raise ValueError("sensor_bus.addresses must be in range 1..247")
        return self


class VentilationMetrics(StrictModel):
    mode: Literal["STOP", "MANUAL", "FAULT"]
    setpoints: FanSetpoints
    hardware_ready: bool
    output_state_known: bool
    consecutive_hardware_failures: int = Field(ge=0)
    active_alarms: list[AlarmState]
    sensor_bus: SensorBusState | None


class VentilationTelemetrySample(StrictModel):
    sample_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    captured_at: AwareDatetime
    metrics: VentilationMetrics


class VentilationTelemetryBatch(StrictModel):
    schema_version: int = Field(ge=1)
    source_id: str = Field(min_length=1, max_length=128)
    batch_id: str = Field(min_length=1, max_length=160)
    created_at: AwareDatetime
    samples: list[VentilationTelemetrySample] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_sample_ids(self) -> "VentilationTelemetryBatch":
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("sample_id values must be unique within a batch")
        return self


class TelemetryBatchAck(StrictModel):
    schema_version: Literal[1] = 1
    source_id: str
    batch_id: str
    status: Literal["accepted"] = "accepted"
    received: int = Field(ge=0)
    stored: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    rejected: int = Field(ge=0)
    server_time: datetime


class HealthComponents(StrictModel):
    database: Literal["ok", "unavailable"]
    ollama: Literal["not_checked"] = "not_checked"


class HealthResponse(StrictModel):
    status: Literal["ok", "unavailable"]
    service: Literal["ai-bridge"] = "ai-bridge"
    version: str
    control_commands_supported: Literal[False] = False
    components: HealthComponents
