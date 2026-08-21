"""Deterministic in-process object storage for tests.

Exists so the upload endpoint can be tested end to end without MinIO running.
It is not a supported way to run the app: ``STEP1_STORAGE_MODE=mock`` keeps
nothing across a restart, which is the opposite of what this task is for.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from threading import Lock

from .base import PresignedURL, StoredObject, storage_uri_for
from .errors import ObjectStorageNotFoundError


DEFAULT_MOCK_BUCKET = "mock-clinical-documents"


class InMemoryObjectStorage:
    """Stores objects in a process-local dict.  Never touches the network."""

    backend_name = "mock-object-storage"

    def __init__(self, *, bucket: str = DEFAULT_MOCK_BUCKET) -> None:
        self.bucket = bucket
        self._lock = Lock()
        self._objects: dict[str, tuple[bytes, StoredObject]] = {}

    def put(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        stored = StoredObject(
            key=key,
            bucket=self.bucket,
            storage_uri=storage_uri_for(self.bucket, key),
            content_type=content_type,
            size_bytes=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
        )
        with self._lock:
            self._objects[key] = (content, stored)
        return stored

    def head(self, *, key: str) -> StoredObject:
        with self._lock:
            entry = self._objects.get(key)
        if entry is None:
            raise ObjectStorageNotFoundError("Stored object was not found.")
        return entry[1]

    def presign_get(
        self,
        *,
        key: str,
        expires_in: int,
        download_filename: str,
    ) -> PresignedURL:
        stored = self.head(key=key)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return PresignedURL(
            # The ``memory://`` scheme is not fetchable on purpose.  A caller
            # that receives one knows immediately it is not talking to MinIO.
            url=(
                f"memory://{self.bucket}/{key}"
                f"?filename={download_filename}"
                f"&expires={int(expires_at.timestamp())}"
            ),
            expires_at=expires_at,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
        )

    def get_content(self, *, key: str) -> bytes:
        """Test helper.  Not part of the ObjectStorage protocol."""

        with self._lock:
            entry = self._objects.get(key)
        if entry is None:
            raise ObjectStorageNotFoundError("Stored object was not found.")
        return entry[0]


__all__ = ["DEFAULT_MOCK_BUCKET", "InMemoryObjectStorage"]
