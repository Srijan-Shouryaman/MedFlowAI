"""S3-compatible object storage with bounded retries and an injectable client.

Works unchanged against MinIO and against AWS S3; the only difference is
configuration (``endpoint_url`` and addressing style).

Only operation metadata is logged.  Object keys embed patient and document
identifiers, so keys are deliberately absent from every log record here.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import PresignedURL, StoredObject, storage_uri_for
from .errors import (
    ObjectStorageConfigurationError,
    ObjectStorageNotFoundError,
    ObjectStorageRequestError,
    ObjectStorageTimeoutError,
)

try:  # Keep the import optional so the module loads without boto3 installed.
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import (
        ConnectTimeoutError,
        EndpointConnectionError,
        ReadTimeoutError,
    )
except ImportError:  # pragma: no cover - exercised only in minimal installs.
    boto3 = None
    BotoConfig = None
    ConnectTimeoutError = None
    EndpointConnectionError = None
    ReadTimeoutError = None


logger = logging.getLogger("medflow.storage")

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})
_CONFIGURATION_CODES = frozenset(
    {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
)


class S3ObjectStorage:
    """Put, head, and presign objects in an S3-compatible bucket.

    ``client`` is duck-typed.  Production injects nothing and a boto3 client is
    built lazily; tests inject a fake and never touch the network.
    """

    backend_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        force_path_style: bool = True,
        sse: str = "none",
        sse_kms_key_id: str | None = None,
        create_bucket_if_missing: bool = False,
        send_checksum: bool = True,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        backoff_seconds: float = 0.1,
    ) -> None:
        if not bucket:
            raise ObjectStorageConfigurationError(
                "S3_BUCKET must be set for the s3 storage backend."
            )
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url or None
        self.access_key_id = access_key_id or None
        self.secret_access_key = secret_access_key or None
        self.force_path_style = force_path_style
        self.sse = (sse or "none").strip()
        self.sse_kms_key_id = sse_kms_key_id or None
        self.create_bucket_if_missing = create_bucket_if_missing
        self.send_checksum = send_checksum
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self.max_retries = max(int(max_retries), 0)
        self._client = client
        self._sleep = sleep
        self._backoff_seconds = max(float(backoff_seconds), 0.0)
        self._bucket_ready = False

    @property
    def client(self) -> Any:
        if self._client is None:
            if boto3 is None:
                raise ObjectStorageConfigurationError(
                    "boto3 is required for the s3 storage backend."
                )
            credentials: dict[str, str] = {}
            # Leave credentials unset so boto3 falls back to its own chain
            # (instance role, shared config) in a real AWS deployment.
            if self.access_key_id and self.secret_access_key:
                credentials = {
                    "aws_access_key_id": self.access_key_id,
                    "aws_secret_access_key": self.secret_access_key,
                }
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self.endpoint_url,
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={
                        "addressing_style": (
                            "path" if self.force_path_style else "auto"
                        )
                    },
                    connect_timeout=self.timeout_seconds,
                    read_timeout=self.timeout_seconds,
                    # Retries are handled here so backoff stays injectable
                    # and deterministic under test.
                    retries={"max_attempts": 1},
                ),
                **credentials,
            )
        return self._client

    def put(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        self._ensure_bucket()
        digest = hashlib.sha256(content).digest()
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
            "ContentLength": len(content),
        }
        if self.send_checksum:
            params["ChecksumSHA256"] = base64.b64encode(digest).decode("ascii")
        params.update(self._encryption_params())

        response = self._call("put_object", lambda: self.client.put_object(**params))
        return StoredObject(
            key=key,
            bucket=self.bucket,
            storage_uri=storage_uri_for(self.bucket, key),
            content_type=content_type,
            size_bytes=len(content),
            checksum_sha256=digest.hex(),
            version_id=(response or {}).get("VersionId"),
        )

    def head(self, *, key: str) -> StoredObject:
        # ChecksumMode is required for the stored checksum to be returned at
        # all; without it the field is silently absent rather than an error.
        response = self._call(
            "head_object",
            lambda: self.client.head_object(
                Bucket=self.bucket,
                Key=key,
                ChecksumMode="ENABLED",
            ),
        ) or {}
        return StoredObject(
            key=key,
            bucket=self.bucket,
            storage_uri=storage_uri_for(self.bucket, key),
            content_type=response.get("ContentType", "application/octet-stream"),
            size_bytes=int(response.get("ContentLength", 0)),
            checksum_sha256=_decode_checksum(response.get("ChecksumSHA256")),
            version_id=response.get("VersionId"),
        )

    def presign_get(
        self,
        *,
        key: str,
        expires_in: int,
        download_filename: str,
    ) -> PresignedURL:
        # head() first so a missing object raises 404 before we hand out a URL
        # that would fail confusingly in the browser.
        stored = self.head(key=key)
        disposition = f'attachment; filename="{download_filename}"'
        # Signing is local; no network call, so no retry loop.
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": stored.content_type,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=expires_in,
        )
        return PresignedURL(
            url=url,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
        )

    def _encryption_params(self) -> dict[str, Any]:
        if self.sse.casefold() in {"", "none"}:
            return {}
        params: dict[str, Any] = {"ServerSideEncryption": self.sse}
        if self.sse.casefold() == "aws:kms" and self.sse_kms_key_id:
            params["SSEKMSKeyId"] = self.sse_kms_key_id
        return params

    def _ensure_bucket(self) -> None:
        if self._bucket_ready or not self.create_bucket_if_missing:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as exc:  # noqa: BLE001 - narrowed by _error_code
            if _error_code(exc) not in _NOT_FOUND_CODES:
                raise self._translate("head_bucket", exc) from exc
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception as create_exc:  # noqa: BLE001
                raise self._translate("create_bucket", create_exc) from create_exc
        self._bucket_ready = True

    def _call(self, operation: str, action: Callable[[], Any]) -> Any:
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                result = action()
            except Exception as exc:  # noqa: BLE001 - re-raised as storage errors
                duration_ms = round((time.monotonic() - started) * 1000, 2)
                if attempt < self.max_retries and _is_retryable(exc):
                    logger.info(
                        "Object storage retry",
                        extra={
                            "backend": self.backend_name,
                            "operation": operation,
                            "attempt": attempt + 1,
                            "duration_ms": duration_ms,
                        },
                    )
                    if self._backoff_seconds:
                        self._sleep(self._backoff_seconds * (2**attempt))
                    attempt += 1
                    continue
                raise self._translate(operation, exc) from exc

            logger.info(
                "Object storage call completed",
                extra={
                    "backend": self.backend_name,
                    "operation": operation,
                    "attempt": attempt + 1,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            return result

    def _translate(self, operation: str, exc: Exception) -> Exception:
        code = _error_code(exc)
        if code in _NOT_FOUND_CODES:
            return ObjectStorageNotFoundError("Stored object was not found.")
        if code in _CONFIGURATION_CODES:
            return ObjectStorageConfigurationError(
                "Object storage rejected the configured credentials."
            )
        if _is_timeout(exc):
            return ObjectStorageTimeoutError(
                f"Object storage timed out during {operation}."
            )
        return ObjectStorageRequestError(
            f"Object storage request failed during {operation}."
        )


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    error = response.get("Error")
    code = error.get("Code", "") if isinstance(error, dict) else ""
    if code:
        return str(code)
    metadata = response.get("ResponseMetadata")
    if isinstance(metadata, dict) and metadata.get("HTTPStatusCode"):
        return str(metadata["HTTPStatusCode"])
    return ""


def _status_code(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return 0
    metadata = response.get("ResponseMetadata")
    if isinstance(metadata, dict):
        try:
            return int(metadata.get("HTTPStatusCode", 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _is_timeout(exc: Exception) -> bool:
    timeout_types = tuple(
        candidate
        for candidate in (ConnectTimeoutError, ReadTimeoutError)
        if candidate is not None
    )
    if timeout_types and isinstance(exc, timeout_types):
        return True
    return "timeout" in type(exc).__name__.casefold()


def _is_retryable(exc: Exception) -> bool:
    if _is_timeout(exc):
        return True
    connection_types = tuple(
        candidate for candidate in (EndpointConnectionError,) if candidate is not None
    )
    if connection_types and isinstance(exc, connection_types):
        return True
    if isinstance(exc, OSError):
        return True
    # Server-side faults are worth another attempt; 4xx never is.
    return _status_code(exc) >= 500


def _decode_checksum(value: str | None) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value).hex()
    except (ValueError, TypeError):
        return ""


__all__ = ["S3ObjectStorage"]
