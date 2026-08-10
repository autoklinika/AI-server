from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VentilationAnalysisResult(StrictAnalysisModel):
    """Small structured envelope around Qwen's natural-language interpretation.

    Python validates only the response shape and basic scalar constraints. It does
    not decide whether the model found enough observations, whether an anomaly is
    justified, or whether particular telemetry fields must be mentioned.
    """

    schema_version: Literal[1] = 1
    status: Literal["normal", "attention", "anomaly", "insufficient_data"]
    summary: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    observations: list[str] = Field(default_factory=list, max_length=30)
    anomalies: list[str] = Field(default_factory=list, max_length=30)
    recommendations: list[str] = Field(default_factory=list, max_length=30)
    data_quality_notes: list[str] = Field(default_factory=list, max_length=30)
