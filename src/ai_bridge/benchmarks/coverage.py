"""Coverage gates for automotive golden datasets."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import ConfigDict, BaseModel, Field

from .contracts import GoldenDataset


class CoveragePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    policy_id: str
    minimum_total: int = Field(ge=1)
    minimum_targets: dict[str, int]
    minimum_languages: dict[str, int]
    minimum_splits: dict[str, int]
    minimum_tags: dict[str, int]
    minimum_unique_evidence_sources: int = Field(ge=1)
    minimum_oem_manifest_sources: int = Field(ge=0)
    declared_gaps: list[str]

    @classmethod
    def load(cls, path: Path) -> "CoveragePolicy":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_coverage(dataset: GoldenDataset, policy: CoveragePolicy) -> dict:
    summary = dataset.summary()
    tags = Counter(tag for case in dataset.cases for tag in case.tags)
    evidence_sources = {
        evidence.source_id
        for case in dataset.cases
        for evidence in case.expected_evidence
    }
    oem_manifest_sources = {
        source_id
        for case in dataset.cases
        for source_id in case.provenance.source_ids
        if source_id.startswith("ASCv0-")
    }

    failures: list[dict] = []

    def minimum(scope: str, key: str, actual: int, required: int) -> None:
        if actual < required:
            failures.append({
                "scope": scope,
                "key": key,
                "actual": actual,
                "required": required,
            })

    minimum("dataset", "total", len(dataset.cases), policy.minimum_total)

    for key, required in policy.minimum_targets.items():
        minimum("target", key, summary["by_target"].get(key, 0), required)
    for key, required in policy.minimum_languages.items():
        minimum("language", key, summary["by_language"].get(key, 0), required)
    for key, required in policy.minimum_splits.items():
        minimum("split", key, summary["by_split"].get(key, 0), required)
    for key, required in policy.minimum_tags.items():
        minimum("tag", key, tags.get(key, 0), required)

    minimum(
        "source",
        "unique_evidence_sources",
        len(evidence_sources),
        policy.minimum_unique_evidence_sources,
    )
    minimum(
        "source",
        "oem_manifest_sources",
        len(oem_manifest_sources),
        policy.minimum_oem_manifest_sources,
    )

    return {
        "schema_version": 1,
        "policy_id": policy.policy_id,
        "status": "pass" if not failures else "fail",
        "summary": summary,
        "tag_counts": dict(sorted(tags.items())),
        "unique_evidence_sources": len(evidence_sources),
        "oem_manifest_sources": len(oem_manifest_sources),
        "failures": failures,
        "declared_gaps": policy.declared_gaps,
    }
