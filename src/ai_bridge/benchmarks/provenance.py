"""Optional cross-repository provenance validation for ERS benchmark sources."""
from __future__ import annotations

import json
from pathlib import Path

from .contracts import GoldenDataset


def _jsonl_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    values = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            payload = json.loads(raw)
            if isinstance(payload.get("id"), str):
                values.add(payload["id"])
    return values


def validate_ers_provenance(dataset: GoldenDataset, ers_root: Path) -> dict:
    corpus = ers_root / "sources" / "automotive-semiconductor-corpus-v0"
    diagnostic_ids = _jsonl_ids(corpus / "DIAGNOSTIC_KNOWLEDGE.jsonl")
    manifest_ids = _jsonl_ids(corpus / "MANIFEST.jsonl")
    network_ids: set[str] = set()
    for facts in (ers_root / "sources").rglob("SOURCE_FACTS.jsonl"):
        network_ids.update(_jsonl_ids(facts))
    case_ids = {
        path.name.split("-", 2)[0] + "-" + path.name.split("-", 2)[1]
        for path in (ers_root / "cases").glob("CASE-*")
        if path.is_dir()
    }

    errors: list[str] = []
    checked = {
        "diagnostic_ids": 0,
        "manifest_ids": 0,
        "network_ids": 0,
        "case_ids": 0,
        "locator_paths": 0,
    }
    for case in dataset.cases:
        source_ids = set(case.provenance.source_ids)
        source_ids.update(evidence.source_id for evidence in case.expected_evidence)
        for source_id in source_ids:
            if source_id.startswith("ERS-DK-"):
                checked["diagnostic_ids"] += 1
                if source_id not in diagnostic_ids:
                    errors.append(f"{case.case_id}: unknown diagnostic source {source_id}")
            elif source_id.startswith("ASCv0-"):
                checked["manifest_ids"] += 1
                if source_id not in manifest_ids:
                    errors.append(f"{case.case_id}: unknown corpus source {source_id}")
            elif source_id.startswith("ERS-NET-"):
                checked["network_ids"] += 1
                if source_id not in network_ids:
                    errors.append(f"{case.case_id}: unknown network source {source_id}")
        for evidence in case.expected_evidence:
            locator_path = evidence.locator.partition("#")[0].strip()
            if (
                "://" not in locator_path
                and locator_path.endswith((".md", ".pdf", ".jsonl"))
            ):
                checked["locator_paths"] += 1
                if not (ers_root / locator_path).is_file():
                    errors.append(
                        f"{case.case_id}: missing evidence locator {locator_path}"
                    )
        for case_id in case.provenance.case_ids:
            checked["case_ids"] += 1
            if case_id not in case_ids:
                errors.append(f"{case.case_id}: unknown ERS case {case_id}")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "status": "pass",
        "ers_root": ers_root.as_posix(),
        "checked": checked,
        "diagnostic_source_count": len(diagnostic_ids),
        "manifest_source_count": len(manifest_ids),
        "network_source_count": len(network_ids),
        "ers_case_count": len(case_ids),
    }
