"""Object storage boundary for original uploaded documents.

The protocol is deliberately narrow.  There is no ``delete`` and no ``list``:
neither has a caller yet, and a delete path in a clinical system needs a
retention and erasure story before it needs an implementation.

Callers depend on this protocol only, never on ``S3ObjectStorage`` directly,
so the MinIO-backed implementation can be swapped for real AWS S3 by changing
configuration rather than code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    bucket: str
    storage_uri: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    version_id: str | None = None


@dataclass(frozen=True)
class PresignedURL:
    url: str
    expires_at: datetime
    content_type: str
    size_bytes: int


class ObjectStorage(Protocol):
    backend_name: str

    def put(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        ...

    def head(self, *, key: str) -> StoredObject:
        ...

    def presign_get(
        self,
        *,
        key: str,
        expires_in: int,
        download_filename: str,
    ) -> PresignedURL:
        ...


def storage_uri_for(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


__all__ = [
    "ObjectStorage",
    "PresignedURL",
    "StoredObject",
    "storage_uri_for",
]
