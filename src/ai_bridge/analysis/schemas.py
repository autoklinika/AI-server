from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VentilationAnalysisResult(StrictAnalysisModel):
    """Minimal, extensible structured envelope for Qwen's advisory report.

    Python validates only the response shape. It does not decide whether a trend
    is normal, abnormal, or operationally important. The contract is intentionally
    small so future stages can add fields without turning the response into a
    complex form the model must fill.
    """

    schema_version: Literal[2] = 2
    status: Literal[
        "no_anomaly_detected",
        "attention",
        "anomaly",
        "insufficient_data",
    ]
    analysis_pl: str = Field(min_length=1, max_length=6000)
    operator_recommendation_pl: str = Field(min_length=1, max_length=3000)
    data_quality_pl: str = Field(min_length=1, max_length=3000)
