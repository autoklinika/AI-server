from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisObservation(StrictAnalysisModel):
    title: str = Field(min_length=1, max_length=200)
    importance: Literal["low", "medium", "high"]
    evidence: list[str] = Field(default_factory=list, max_length=12)


class AnalysisAnomaly(StrictAnalysisModel):
    title: str = Field(min_length=1, max_length=200)
    severity: Literal["low", "medium", "high", "critical"]
    description: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    probable_causes: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)


class AnalysisRecommendation(StrictAnalysisModel):
    priority: Literal["low", "medium", "high"]
    recommendation: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1500)
    operator_action_required: bool


class VentilationAnalysisResult(StrictAnalysisModel):
    schema_version: Literal[1] = 1
    status: Literal["normal", "attention", "anomaly", "insufficient_data"]
    summary: str = Field(min_length=1, max_length=3000)
    confidence: float = Field(ge=0.0, le=1.0)
    observations: list[AnalysisObservation] = Field(default_factory=list, max_length=20)
    anomalies: list[AnalysisAnomaly] = Field(default_factory=list, max_length=20)
    recommendations: list[AnalysisRecommendation] = Field(default_factory=list, max_length=20)
    data_quality_notes: list[str] = Field(default_factory=list, max_length=20)
