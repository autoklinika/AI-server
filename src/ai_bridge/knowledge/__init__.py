"""Knowledge Service boundary. Product-specific backends stay behind adapters."""

from .canonical import (
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeDocumentVersionRecord,
    KnowledgeSourceRecord,
    chunk_record,
    document_record,
    document_version_record,
    source_record,
)
from .service import KnowledgeContractError, KnowledgeService

__all__ = [
    "KnowledgeChunkRecord",
    "KnowledgeContractError",
    "KnowledgeDocumentRecord",
    "KnowledgeDocumentVersionRecord",
    "KnowledgeService",
    "KnowledgeSourceRecord",
    "chunk_record",
    "document_record",
    "document_version_record",
    "source_record",
]
