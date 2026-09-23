"""Knowledge Service boundary. Product-specific backends stay behind adapters."""

from .service import KnowledgeContractError, KnowledgeService

__all__ = ["KnowledgeContractError", "KnowledgeService"]
