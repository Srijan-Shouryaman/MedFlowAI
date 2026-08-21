"""Storage backend selection.

The mode is read from the environment and never raises at construction time.
It defaults to ``s3`` because persisting to MinIO is the entire point of this
service; a mock default would let the app look healthy while storing nothing.
"""

from __future__ import annotations

import logging

from .base import ObjectStorage
from .config import env_bool, env_clamped_int, env_int, env_value
from .mock import InMemoryObjectStorage
from .s3 import S3ObjectStorage


logger = logging.getLogger("medflow.storage")

DEFAULT_BUCKET = "medflow-documents"
DEFAULT_PRESIGN_EXPIRY_SECONDS = 300
MIN_PRESIGN_EXPIRY_SECONDS = 60
MAX_PRESIGN_EXPIRY_SECONDS = 3600


def configured_presign_expiry() -> int:
    return env_clamped_int(
        "S3_PRESIGN_EXPIRY_SECONDS",
        DEFAULT_PRESIGN_EXPIRY_SECONDS,
        minimum=MIN_PRESIGN_EXPIRY_SECONDS,
        maximum=MAX_PRESIGN_EXPIRY_SECONDS,
    )


def build_object_storage(mode: str | None = None) -> ObjectStorage:
    selected_mode = (mode or env_value("STEP1_STORAGE_MODE", "s3") or "s3").lower()

    if selected_mode == "mock":
        logger.warning(
            "Object storage is in mock mode; uploads will not reach MinIO "
            "and are lost on restart."
        )
        return InMemoryObjectStorage()

    if selected_mode != "s3":
        logger.warning(
            "Unknown object storage mode; falling back to mock storage.",
            extra={"mode": selected_mode},
        )
        return InMemoryObjectStorage()

    storage = S3ObjectStorage(
        bucket=env_value("S3_BUCKET", DEFAULT_BUCKET) or DEFAULT_BUCKET,
        region=env_value("S3_REGION", "us-east-1") or "us-east-1",
        endpoint_url=env_value("S3_ENDPOINT_URL"),
        access_key_id=env_value("S3_ACCESS_KEY_ID"),
        secret_access_key=env_value("S3_SECRET_ACCESS_KEY"),
        force_path_style=env_bool("S3_FORCE_PATH_STYLE", True),
        sse=env_value("S3_SSE", "none") or "none",
        sse_kms_key_id=env_value("S3_SSE_KMS_KEY_ID"),
        create_bucket_if_missing=env_bool("S3_CREATE_BUCKET_IF_MISSING", False),
        send_checksum=env_bool("S3_SEND_CHECKSUM", True),
        timeout_seconds=env_int("S3_TIMEOUT_SECONDS", 10, minimum=1),
        max_retries=env_int("S3_MAX_RETRIES", 2),
    )
    logger.info(
        "Object storage configured",
        extra={
            "backend": storage.backend_name,
            "bucket": storage.bucket,
            "endpoint_url": storage.endpoint_url or "aws-default",
        },
    )
    return storage


__all__ = [
    "DEFAULT_BUCKET",
    "DEFAULT_PRESIGN_EXPIRY_SECONDS",
    "MAX_PRESIGN_EXPIRY_SECONDS",
    "MIN_PRESIGN_EXPIRY_SECONDS",
    "build_object_storage",
    "configured_presign_expiry",
]
