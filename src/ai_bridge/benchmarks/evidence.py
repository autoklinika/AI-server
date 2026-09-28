"""Resolve fixed benchmark evidence without using retrieval."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import ExpectedEvidence, GoldenCase


@dataclass(frozen=True)
class ResolvedEvidence:
    source_id: str
    locator: str
    text: str


def _fold_heading(value: str) -> str:
    value = value.casefold().replace("²", "2")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _markdown_section(text: str, anchor: str | None) -> str:
    if not anchor:
        return text.strip()
    target = _fold_heading(anchor)
    lines = text.splitlines()
    start = None
    level = None

    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and _fold_heading(match.group(2)) == target:
            start = index
            level = len(match.group(1))
            break
    if start is None:
        return text.strip()
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def _find_jsonl_record(root: Path, source_id: str) -> str | None:
    for path in root.rglob("*.jsonl"):
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if row.get("id") == source_id:
                    return json.dumps(row, ensure_ascii=False, sort_keys=True)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def _resolve_locator(locator: str, roots: tuple[Path, ...]) -> str | None:
    path_part, _, anchor = locator.partition("#")
    if not path_part or " p." in path_part or " pp." in path_part:
        return None
    for root in roots:
        path = root / path_part
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                payload = path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                return (
                    "[BINARY EVIDENCE NOT EMBEDDED]\n"
                    f"filename: {path.name}\n"
                    f"byte_size: {len(payload)}\n"
                    f"sha256: {digest}"
                )
            return _markdown_section(text, anchor or None)
    return None


def resolve_evidence(
    case: GoldenCase,
    *,
    ai_root: Path,
    ers_root: Path,
    max_chars_per_source: int = 8000,
) -> tuple[ResolvedEvidence, ...]:
    roots = (ers_root, ai_root)
    resolved: list[ResolvedEvidence] = []
    for evidence in case.expected_evidence:
        text = _find_jsonl_record(ers_root, evidence.source_id)
        if text is None:
            text = _resolve_locator(evidence.locator, roots)
        if text is None:
            raise ValueError(
                f"{case.case_id}: cannot resolve fixed evidence "
                f"{evidence.source_id} at {evidence.locator}"
            )

        resolved.append(ResolvedEvidence(
            source_id=evidence.source_id,
            locator=evidence.locator,
            text=text[:max_chars_per_source],
        ))
    return tuple(resolved)


def render_fixed_evidence(case: GoldenCase, evidence: tuple[ResolvedEvidence, ...]) -> str:
    blocks = []
    for item in evidence:
        blocks.append(
            f"[SOURCE {item.source_id}]\n"
            f"Locator: {item.locator}\n"
            f"{item.text}"
        )
    context = "\n\n".join(blocks)
    history = ""
    if case.context_turns:
        rendered = "\n".join(
            f"{turn.role.upper()}: {turn.content}" for turn in case.context_turns
        )
        history = f"Conversation context:\n{rendered}\n\n"
    return (
        "Answer the technical benchmark question using ONLY the supplied evidence. "
        "Do not infer unsupported device-specific facts. If evidence is insufficient, "
        "say so explicitly. Cite source IDs exactly as provided.\n\n"
        f"{history}Question:\n{case.question}\n\nEvidence:\n{context}"
    )
