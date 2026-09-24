from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_bridge.storage.object_store import (
    FileObjectStore,
    ObjectStoreCorruption,
    StoredObject,
)


ContentStoreCorruption = ObjectStoreCorruption
StoredContent = StoredObject


@dataclass(frozen=True)
class FileContentStore:
    """Stage J compatibility adapter over the shared platform ObjectStore."""

    root: Path

    @property
    def _store(self) -> FileObjectStore:
        return FileObjectStore(self.root)

    def put(self, content: bytes) -> StoredContent:
        return self._store.put(content)

    def verify(self, uri: str, expected_sha256: str) -> None:
        self._store.verify_uri(uri, expected_sha256)
