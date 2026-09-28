"""Model-independent contracts for AI Platform benchmark datasets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Target = Literal["llm", "router", "retrieval_rag"]
Difficulty = Literal["easy", "medium", "hard", "adversarial"]
Language = Literal["pl", "en", "bilingual"]
EvaluationSplit = Literal["dev", "holdout", "challenge"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedFact(StrictModel):
    fact_id: str
    statement: str
    required: bool = True


class ExpectedEvidence(StrictModel):
    source_id: str
    locator: str
    supports_fact_ids: list[str] = Field(min_length=1)


class AcceptableAnswer(StrictModel):
    reference: str
    required_concepts: list[str] = Field(min_length=1)
    optional_concepts: list[str] = Field(default_factory=list)


class RoutingExpectation(StrictModel):
    primary: Literal[
        "reasoning", "knowledge_rag", "graphify", "telemetry", "vision", "tool"
    ]
    requires_knowledge: bool = False
    requires_graph: bool = False
    requires_vision: bool = False
    expected_tools: list[str] = Field(default_factory=list)


class GroundingExpectation(StrictModel):
    must_cite: bool = True
    minimum_source_coverage: float = Field(ge=0.0, le=1.0)
    fail_closed_if_missing: bool = True


class ConfidenceExpectation(StrictModel):
    grounded_min: float = Field(ge=0.0, le=1.0)
    ungrounded_max: float = Field(ge=0.0, le=1.0)


class Provenance(StrictModel):
    source_repo: str
    source_ids: list[str] = Field(min_length=1)
    case_ids: list[str] = Field(default_factory=list)
    source_commit: str | None = None
    reuse_status: str | None = None


class GoldenCase(StrictModel):
    schema_version: Literal[1]
    case_id: str
    targets: list[Target] = Field(min_length=1)
    question: str
    category: str
    difficulty: Difficulty
    language: Language
    split: EvaluationSplit
    training_exclusion: Literal[True]
    expected_facts: list[ExpectedFact] = Field(min_length=1)
    expected_evidence: list[ExpectedEvidence] = Field(min_length=1)
    acceptable_answer: AcceptableAnswer
    forbidden_claims: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    expected_routing: RoutingExpectation
    grounding: GroundingExpectation
    expected_confidence: ConfidenceExpectation
    provenance: Provenance
    tags: list[str] = Field(default_factory=list)


    @model_validator(mode="after")
    def validate_evidence_links(self) -> "GoldenCase":
        fact_ids = {fact.fact_id for fact in self.expected_facts}
        referenced = {
            fact_id
            for evidence in self.expected_evidence
            for fact_id in evidence.supports_fact_ids
        }
        unknown = referenced - fact_ids
        if unknown:
            raise ValueError(f"evidence references unknown facts: {sorted(unknown)}")
        required = {fact.fact_id for fact in self.expected_facts if fact.required}
        if not required.issubset(referenced):
            missing = sorted(required - referenced)
            raise ValueError(f"required facts without evidence: {missing}")
        return self


class GoldenDataset:
    def __init__(self, cases: list[GoldenCase]):
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate benchmark case_id")
        self.cases = tuple(cases)

    @classmethod
    def load_jsonl(cls, path: Path) -> "GoldenDataset":
        rows: list[GoldenCase] = []

        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
                rows.append(GoldenCase.model_validate(payload))
            except Exception as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
        if not rows:
            raise ValueError("golden dataset is empty")
        return cls(rows)

    def summary(self) -> dict:
        by_target = {target: 0 for target in ("llm", "router", "retrieval_rag")}
        by_language: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_split: dict[str, int] = {}
        for case in self.cases:
            for target in case.targets:
                by_target[target] += 1
            by_language[case.language] = by_language.get(case.language, 0) + 1
            by_category[case.category] = by_category.get(case.category, 0) + 1
            by_split[case.split] = by_split.get(case.split, 0) + 1
        return {
            "schema_version": 1,
            "case_count": len(self.cases),
            "by_target": by_target,
            "by_language": dict(sorted(by_language.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_split": dict(sorted(by_split.items())),
        }


class SuiteManifest(StrictModel):
    schema_version: Literal[1]
    suite_id: str
    benchmark_class: Target
    version: str
    status: Literal["foundation", "ready", "deprecated"]
    objective: str
    dataset: str
    metrics: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(min_length=1)
    tracks: list[str] = Field(min_length=1)
    candidate_models: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "SuiteManifest":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
