"""Versioned baseline-matrix contracts."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import StrictModel


class MatrixRun(StrictModel):
    suite: str
    track: str
    subject: str


class MatrixPhase(StrictModel):
    phase_id: str
    split: Literal["dev", "holdout", "challenge"]
    runs: list[MatrixRun] = Field(default_factory=list)
    inherits_tracks_from: list[str] = Field(default_factory=list)


class MatrixPolicy(StrictModel):
    training_allowed: Literal[False]
    holdout_after_dev_gate: bool
    challenge_after_holdout_gate: bool
    resource_scope: Literal["system"]
    require_dataset_hash_lock: bool


class MatrixAcceptance(StrictModel):
    completion_rate: float = Field(ge=0.0, le=1.0)
    failed_cases: int = Field(ge=0)
    require_per_track_metrics: bool
    require_latency: bool
    require_resource_telemetry: bool
    forbid_single_aggregate_verdict: bool


class BaselineMatrix(StrictModel):
    schema_version: Literal[1]
    matrix_id: str
    dataset: str
    policy: MatrixPolicy
    phases: list[MatrixPhase] = Field(min_length=1)
    acceptance: MatrixAcceptance

    @classmethod
    def load(cls, path: Path) -> "BaselineMatrix":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @model_validator(mode="after")
    def validate_order(self) -> "BaselineMatrix":
        ids = [phase.phase_id for phase in self.phases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate phase_id")
        by_id = {phase.phase_id: phase for phase in self.phases}
        for phase in self.phases:
            if not phase.runs and not phase.inherits_tracks_from:
                raise ValueError(f"{phase.phase_id}: phase has no runs or inheritance")
            missing = set(phase.inherits_tracks_from) - set(by_id)
            if missing:
                raise ValueError(
                    f"{phase.phase_id}: unknown inherited phases {sorted(missing)}"
                )
        return self
