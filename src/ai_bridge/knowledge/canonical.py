from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import re
from types import MappingProxyType
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def stable_id(prefix: str, *parts: str) -> str:
    if not prefix or any(not part for part in parts):
        raise ValueError("stable_id requires non-empty prefix and parts")
    digest = sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _require(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} is required")

def _require_sha256(value: str, name: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _freeze_mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


def _optional_nonempty(value: str | None, name: str) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{name} must be non-empty when provided")


@dataclass(frozen=True)
class KnowledgeSourceRecord:
    """Stable origin/authority from which logical documents are acquired."""

    source_id: str
    domain: str
    namespace: str
    source_type: str
    uri: str
    title: str | None = None
    acl_policy_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_id", "domain", "namespace", "source_type", "uri"):
            _require(getattr(self, name), name)
        _optional_nonempty(self.title, "title")
        _optional_nonempty(self.acl_policy_id, "acl_policy_id")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    """Logical document identity independent of any particular revision."""

    document_id: str
    source_id: str
    uri: str
    title: str
    media_type: str
    language: str | None = None
    acl_policy_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("document_id", "source_id", "uri", "title", "media_type"):
            _require(getattr(self, name), name)
        _optional_nonempty(self.language, "language")
        _optional_nonempty(self.acl_policy_id, "acl_policy_id")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class KnowledgeDocumentVersionRecord:
    """Immutable content revision used as the canonical reindex boundary."""

    version_id: str
    document_id: str
    content_sha256: str
    byte_size: int
    storage_uri: str
    source_revision: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("version_id", "document_id", "storage_uri"):
            _require(getattr(self, name), name)
        _require_sha256(self.content_sha256, "content_sha256")
        _optional_nonempty(self.source_revision, "source_revision")
        if self.byte_size < 0:
            raise ValueError("byte_size must be >= 0")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class KnowledgeChunkRecord:
    """Canonical text unit. Vector indexes are disposable projections of this record."""

    chunk_id: str
    version_id: str
    ordinal: int
    text: str
    text_sha256: str
    locator: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(self.chunk_id, "chunk_id")
        _require(self.version_id, "version_id")
        _require(self.text, "text")
        _require_sha256(self.text_sha256, "text_sha256")
        if sha256_text(self.text) != self.text_sha256:
            raise ValueError("text_sha256 does not match text")
        if self.ordinal < 0:
            raise ValueError("ordinal must be >= 0")
        object.__setattr__(self, "locator", _freeze_mapping(self.locator, "locator"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


def source_record(
    *, domain: str, namespace: str, source_type: str, uri: str,
    title: str | None = None, acl_policy_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> KnowledgeSourceRecord:
    return KnowledgeSourceRecord(
        source_id=stable_id("ksrc", domain, namespace, source_type, uri),
        domain=domain,
        namespace=namespace,
        source_type=source_type,
        uri=uri,
        title=title,
        acl_policy_id=acl_policy_id,
        metadata={} if metadata is None else metadata,
    )


def document_record(
    source: KnowledgeSourceRecord, *, uri: str, title: str, media_type: str,
    language: str | None = None, acl_policy_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> KnowledgeDocumentRecord:
    return KnowledgeDocumentRecord(
        document_id=stable_id("kdoc", source.source_id, uri),
        source_id=source.source_id,
        uri=uri,
        title=title,
        media_type=media_type,
        language=language,
        acl_policy_id=source.acl_policy_id if acl_policy_id is None else acl_policy_id,
        metadata={} if metadata is None else metadata,
    )


def document_version_record(
    document: KnowledgeDocumentRecord, *, content_sha256: str, byte_size: int,
    storage_uri: str, source_revision: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> KnowledgeDocumentVersionRecord:
    return KnowledgeDocumentVersionRecord(
        version_id=stable_id("kver", document.document_id, content_sha256),
        document_id=document.document_id,
        content_sha256=content_sha256,
        byte_size=byte_size,
        storage_uri=storage_uri,
        source_revision=source_revision,
        metadata={} if metadata is None else metadata,
    )


def chunk_record(
    version: KnowledgeDocumentVersionRecord, *, ordinal: int, text: str,
    locator: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> KnowledgeChunkRecord:
    digest = sha256_text(text)
    return KnowledgeChunkRecord(
        chunk_id=stable_id("kchk", version.version_id, str(ordinal), digest),
        version_id=version.version_id,
        ordinal=ordinal,
        text=text,
        text_sha256=digest,
        locator={} if locator is None else locator,
        metadata={} if metadata is None else metadata,
    )
