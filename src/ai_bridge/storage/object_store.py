from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_sha256(digest: str) -> str:
    if not _SHA256.fullmatch(digest):
        raise ValueError("digest must be lowercase SHA-256 hex")
    return digest


class ObjectStoreError(RuntimeError):
    pass


class ObjectStoreCorruption(ObjectStoreError):
    pass


class ObjectStoreNotFound(ObjectStoreError, FileNotFoundError):
    pass


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    byte_size: int
    uri: str


class ObjectStore(Protocol):
    def put(self, content: bytes) -> StoredObject: ...
    def exists(self, digest: str) -> bool: ...
    def verify(self, digest: str) -> StoredObject: ...
    def read(self, digest: str) -> bytes: ...


@dataclass(frozen=True)
class FileObjectStore:
    root: Path

    validate_digest = staticmethod(validate_sha256)

    def path_for(self, digest: str) -> Path:
        digest = self.validate_digest(digest)
        return self.root / "sha256" / digest[:2] / digest

    def put(self, content: bytes) -> StoredObject:
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return self.verify(digest)

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
            actual = sha256(tmp.read_bytes()).hexdigest()
            if actual != digest:
                raise ObjectStoreCorruption(
                    f"temporary object checksum mismatch: expected={digest} actual={actual}"
                )
            os.replace(tmp, target)
            target.chmod(0o444)
        finally:
            if tmp.exists():
                tmp.unlink()

        return StoredObject(
            sha256=digest,
            byte_size=len(content),
            uri=target.resolve().as_uri(),
        )

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def verify(self, digest: str) -> StoredObject:
        digest = self.validate_digest(digest)
        path = self.path_for(digest)
        if not path.is_file():
            raise ObjectStoreNotFound(digest)
        content = path.read_bytes()
        actual = sha256(content).hexdigest()
        if actual != digest:
            raise ObjectStoreCorruption(
                f"object checksum mismatch: expected={digest} actual={actual}"
            )
        return StoredObject(
            sha256=digest,
            byte_size=len(content),
            uri=path.resolve().as_uri(),
        )

    def verify_uri(self, uri: str, expected_sha256: str) -> StoredObject:
        expected_sha256 = self.validate_digest(expected_sha256)
        prefix = "file://"
        if not uri.startswith(prefix):
            raise ValueError("FileObjectStore supports only file:// URIs")
        path = Path(uri[len(prefix):]).resolve()
        expected_path = self.path_for(expected_sha256).resolve()
        if path != expected_path:
            raise ObjectStoreCorruption(
                "storage URI does not match content-addressed object path"
            )
        return self.verify(expected_sha256)

    def read(self, digest: str) -> bytes:
        stored = self.verify(digest)
        return Path(stored.uri.removeprefix("file://")).read_bytes()

    def open_path(self, digest: str) -> Path:
        stored = self.verify(digest)
        return Path(stored.uri.removeprefix("file://"))
