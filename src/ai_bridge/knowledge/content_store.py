from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import tempfile


class ContentStoreCorruption(RuntimeError):
    """Stored content does not match its content-addressed path."""


@dataclass(frozen=True)
class StoredContent:
    sha256: str
    byte_size: int
    uri: str


@dataclass(frozen=True)
class FileContentStore:
    root: Path

    def put(self, content: bytes) -> StoredContent:
        digest = sha256(content).hexdigest()
        target = self.root / "sha256" / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            existing = target.read_bytes()
            if sha256(existing).hexdigest() != digest:
                raise ContentStoreCorruption(
                    f"content-addressed object is corrupt: {target}"
                )
            return StoredContent(
                sha256=digest,
                byte_size=len(existing),
                uri=target.resolve().as_uri(),
            )

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{digest}.",
            dir=str(target.parent),
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, target)
            target.chmod(0o444)
        finally:
            if tmp.exists():
                tmp.unlink()

        return StoredContent(
            sha256=digest,
            byte_size=len(content),
            uri=target.resolve().as_uri(),
        )

    def verify(self, uri: str, expected_sha256: str) -> None:
        prefix = "file://"
        if not uri.startswith(prefix):
            raise ValueError("FileContentStore can verify only file:// URIs")
        path = Path(uri[len(prefix):])
        content = path.read_bytes()
        actual = sha256(content).hexdigest()
        if actual != expected_sha256:
            raise ContentStoreCorruption(
                f"object checksum mismatch: expected={expected_sha256} actual={actual}"
            )
