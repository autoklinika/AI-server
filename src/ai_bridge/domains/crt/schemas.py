from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
URI = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"^[a-zA-Z][a-zA-Z0-9+.-]*:")]


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def content_hash(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class Contract(BaseModel):
    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("unsupported schema version; supported: 1")
        return value

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Wire(Contract):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FileReference(Wire):
    relative_path: str = Field(min_length=1, max_length=1024)
    sha256: Digest
    bytes: int = Field(ge=0, le=2**63-1)
    media_type: Identifier
    role: Identifier

    @field_validator("relative_path")
    @classmethod
    def relative(cls, value):
        if PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive or "\\" in value or ".." in value.split("/"):
            raise ValueError("expected project-relative path without traversal")
        return value


class ArtifactSource(Wire):
    session_id: Identifier
    source_kind: Identifier
    source_reference: dict[str, JsonValue]


class Artifact(Wire):
    # Artifact schemas belong to their providers, not the platform envelope.
    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int or value < 1:
            raise ValueError("invalid artifact schema version")
        return value

    id: Identifier
    analysis_run_id: Identifier
    artifact_type: Identifier
    schema_version: int
    provider_id: Identifier
    provider_version: Identifier
    algorithm_version: Identifier
    sources: list[ArtifactSource] = Field(min_length=1, max_length=128, strict=False)
    sha256: Digest
    metadata: dict[str, JsonValue]
    created_at_utc: str
    file: FileReference

    @model_validator(mode="after")
    def verify_file(self):
        if self.sha256 != self.file.sha256:
            raise ValueError("artifact file hash mismatch")
        return self


class Source(Wire):
    kind: str
    header_source: str
    started_at_utc: str
    adapter: str
    bitrate: int | None
    channel: int | None


class TimeBounds(Wire):
    min_timestamp_ns: int | None
    max_timestamp_ns: int | None
    clock: str


class Provenance(Wire):
    session_schema_id: str
    session_schema_version: int
    decoder: str


class Manifest(Wire):
    schema_id: Literal["crt.platform.session-export"]
    schema_version: Literal[1]
    algorithm_version: Identifier
    project_id: Identifier
    session_id: Identifier
    source: Source
    capture_mode: str
    time_bounds: TimeBounds
    frame_count: int = Field(ge=0, le=2**63-1)
    catalog_frame_count: int = Field(ge=0, le=2**63-1)
    files: list[FileReference] = Field(min_length=1, max_length=128)
    artifacts: list[Artifact] = Field(max_length=128)
    provenance: Provenance
    omitted_data: list[str]
    limitations: list[str]

    @property
    def manifest_hash(self):
        return content_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def verify(self):
        if len(canonical(self.model_dump(mode="json"))) > 1048576:
            raise ValueError("manifest exceeds 1 MiB")
        if len({a.id for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate artifact id")
        if len({f.relative_path for f in self.files}) != len(self.files):
            raise ValueError("duplicate file path")
        if any(s.session_id != self.session_id for a in self.artifacts for s in a.sources):
            raise ValueError("artifact references another session")
        return self


class LinkRequest(Contract):
    case_id: UUID
    role: Identifier
    actor_id: Identifier


class UnlinkRequest(Contract):
    actor_id: Identifier


class Evidence(Wire):
    artifact: Artifact
    selected_payload: JsonValue


class AIContext(Wire):
    schema_id: Literal["crt.platform.ai-context"]
    schema_version: Literal[1]
    algorithm_version: Identifier
    project_id: Identifier
    session_id: Identifier
    manifest_sha256: Digest
    source_files: list[FileReference] = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2048)
    evidence: list[Evidence] = Field(max_length=16)
    omitted_data: list[str]
    limitations: list[str]
    maximum_bytes: int = Field(gt=0, le=1048576)

    @model_validator(mode="after")
    def bounded(self):
        if not self.question.strip():
            raise ValueError("question required")
        if len(canonical(self.model_dump(mode="json"))) > self.maximum_bytes:
            raise ValueError("context exceeds maximum_bytes (at most 1 MiB)")
        if len({e.artifact.id for e in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate context evidence")
        return self


class Hypothesis(Contract):
    statement: str = Field(min_length=1, max_length=8192)
    confidence: float | None = Field(default=None, ge=0, le=1)


class KnowledgeReference(Contract):
    document_id: Identifier
    version_id: Identifier
    chunk_id: Identifier | None = None
    content_sha256: Digest


class FindingRequest(Hypothesis):
    knowledge_refs: list[KnowledgeReference] = Field(default_factory=list, max_length=16)
    provider: Identifier
    model: Identifier
    context: AIContext
    context_hash: Digest
    status: Literal["suggested", "to_review"] = "suggested"
    actor_id: Identifier

    @model_validator(mode="after")
    def verify_context(self):
        if content_hash(self.context.model_dump(mode="json")) != self.context_hash:
            raise ValueError("context hash mismatch")
        return self


class AnalysisRequest(Contract):
    context: AIContext
    actor_id: Identifier
