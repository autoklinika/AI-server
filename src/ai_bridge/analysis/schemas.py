from __future__ import annotations

from datetime import datetime
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


class VentilationAnalysisDelivery(StrictAnalysisModel):
    """Read-only envelope delivered to CM5/operator-facing clients.

    The safety flags are constants by contract. This endpoint only exposes a
    previously stored analysis result; it never invokes Qwen and never carries
    a control command.
    """

    delivery_schema_version: Literal[1] = 1
    analysis_id: str = Field(min_length=1, max_length=36)
    source_id: str = Field(min_length=1, max_length=128)
    window_start: datetime
    window_end: datetime
    created_at: datetime
    sample_count: int = Field(ge=0)
    model: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)
    advisory_only: Literal[True] = True
    experimental: Literal[True] = True
    control_actions_supported: Literal[False] = False
    result: VentilationAnalysisResult
