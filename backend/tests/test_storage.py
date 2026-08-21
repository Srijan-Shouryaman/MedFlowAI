"""Unit tests for the storage boundary: keys, mock backend, and S3 wiring."""

from __future__ import annotations

import base64
import hashlib
from uuid import UUID, uuid4

import pytest

from app.storage.errors import (
    ObjectStorageNotFoundError,
    ObjectStorageRequestError,
    ObjectStorageTimeoutError,
)
from app.storage.factory import build_object_storage, configured_presign_expiry
from app.storage.keys import (
    UnsafeIdentifierError,
    build_source_key,
    download_filename,
)
from app.storage.mock import InMemoryObjectStorage
from app.storage.s3 import S3ObjectStorage


DOCUMENT_ID = UUID("11111111-2222-3333-4444-555555555555")


class FakeS3Client:
    def __init__(self, *, fail_times: int = 0, error: Exception | None = None) -> None:
        self.puts: list[dict] = []
        self.head_calls: list[dict] = []
        self._fail_times = fail_times
        self._error = error or _server_error()

    def put_object(self, **params):
        self.puts.append(params)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise self._error
        return {"VersionId": "v1"}

    def head_object(self, **params):
        self.head_calls.append(params)
        content = self.puts[-1]["Body"]
        return {
            "ContentType": self.puts[-1]["ContentType"],
            "ContentLength": len(content),
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(content).digest()).decode(),
        }

    def generate_presigned_url(self, _operation, Params, ExpiresIn):  # noqa: N803
        return f"https://example.invalid/{Params['Key']}?expires={ExpiresIn}"


def _server_error() -> Exception:
    error = Exception("boom")
    error.response = {"ResponseMetadata": {"HTTPStatusCode": 500}}
    return error


def _not_found_error() -> Exception:
    error = Exception("missing")
    error.response = {"Error": {"Code": "NoSuchKey"}}
    return error


class TestKeys:
    def test_key_is_a_pure_function_of_patient_and_document(self) -> None:
        key = build_source_key(patient_id="pat_00123", document_id=DOCUMENT_ID)
        assert key == f"step1/patients/pat_00123/documents/{DOCUMENT_ID}/source"
        assert build_source_key(patient_id="pat_00123", document_id=DOCUMENT_ID) == key

    def test_key_carries_no_filename_or_extension(self) -> None:
        key = build_source_key(patient_id="pat_00123", document_id=DOCUMENT_ID)
        assert key.endswith("/source")
        assert "." not in key.rsplit("/", 1)[-1]

    @pytest.mark.parametrize(
        "patient_id",
        ["../escape", "pat/00123", "", "   ", "pat\x00123", "a" * 100],
    )
    def test_unsafe_patient_ids_are_rejected(self, patient_id: str) -> None:
        with pytest.raises(UnsafeIdentifierError):
            build_source_key(patient_id=patient_id, document_id=DOCUMENT_ID)

    def test_download_filename_uses_document_id_not_upload_name(self) -> None:
        assert download_filename(DOCUMENT_ID, "image/png") == f"{DOCUMENT_ID}.png"
        assert download_filename(DOCUMENT_ID, "application/pdf") == f"{DOCUMENT_ID}.pdf"
        assert download_filename(DOCUMENT_ID, "application/x-thing") == str(DOCUMENT_ID)


class TestInMemoryStorage:
    def test_put_then_head_round_trips(self) -> None:
        storage = InMemoryObjectStorage(bucket="b")
        stored = storage.put(key="k", content=b"hello", content_type="text/plain")
        assert stored.storage_uri == "s3://b/k"
        assert stored.checksum_sha256 == hashlib.sha256(b"hello").hexdigest()
        assert storage.head(key="k").size_bytes == 5
        assert storage.get_content(key="k") == b"hello"

    def test_head_of_missing_key_raises_not_found(self) -> None:
        with pytest.raises(ObjectStorageNotFoundError):
            InMemoryObjectStorage().head(key="absent")


class TestS3Storage:
    def _storage(self, client) -> S3ObjectStorage:
        return S3ObjectStorage(
            bucket="bucket",
            client=client,
            sleep=lambda _seconds: None,
            backoff_seconds=0,
        )

    def test_put_sends_checksum_and_content_type(self) -> None:
        client = FakeS3Client()
        stored = self._storage(client).put(
            key="k", content=b"hello", content_type="text/plain"
        )
        params = client.puts[0]
        assert params["ContentType"] == "text/plain"
        assert params["ContentLength"] == 5
        assert params["ChecksumSHA256"] == base64.b64encode(
            hashlib.sha256(b"hello").digest()
        ).decode()
        assert stored.checksum_sha256 == hashlib.sha256(b"hello").hexdigest()
        assert stored.version_id == "v1"

    def test_head_requests_the_stored_checksum(self) -> None:
        # Without ChecksumMode the field is silently absent from the response
        # rather than an error, so this assertion is the only thing standing
        # between us and a permanently empty checksum.
        client = FakeS3Client()
        storage = self._storage(client)
        storage.put(key="k", content=b"hello", content_type="text/plain")
        stored = storage.head(key="k")
        assert client.head_calls[0]["ChecksumMode"] == "ENABLED"
        assert stored.checksum_sha256 == hashlib.sha256(b"hello").hexdigest()

    def test_server_errors_are_retried_then_succeed(self) -> None:
        client = FakeS3Client(fail_times=2)
        stored = self._storage(client).put(
            key="k", content=b"x", content_type="text/plain"
        )
        assert len(client.puts) == 3
        assert stored.size_bytes == 1

    def test_retries_are_bounded(self) -> None:
        client = FakeS3Client(fail_times=99)
        with pytest.raises(ObjectStorageRequestError):
            self._storage(client).put(key="k", content=b"x", content_type="text/plain")
        assert len(client.puts) == 3  # initial attempt plus max_retries=2

    def test_not_found_is_not_retried(self) -> None:
        client = FakeS3Client(fail_times=99, error=_not_found_error())
        with pytest.raises(ObjectStorageNotFoundError):
            self._storage(client).put(key="k", content=b"x", content_type="text/plain")
        assert len(client.puts) == 1

    def test_timeouts_translate_to_a_timeout_error(self) -> None:
        class ReadTimeout(Exception):
            pass

        client = FakeS3Client(fail_times=99, error=ReadTimeout())
        with pytest.raises(ObjectStorageTimeoutError):
            self._storage(client).put(key="k", content=b"x", content_type="text/plain")

    def test_presign_includes_a_download_disposition(self) -> None:
        client = FakeS3Client()
        storage = self._storage(client)
        storage.put(key="k", content=b"hello", content_type="text/plain")
        presigned = storage.presign_get(
            key="k", expires_in=300, download_filename="doc.txt"
        )
        assert presigned.url.startswith("https://example.invalid/k")
        assert presigned.content_type == "text/plain"
        assert presigned.size_bytes == 5


class TestFactory:
    def test_defaults_to_s3_so_mock_storage_is_never_silent(self, monkeypatch) -> None:
        monkeypatch.delenv("STEP1_STORAGE_MODE", raising=False)
        monkeypatch.setenv("S3_BUCKET", "b")
        assert build_object_storage().backend_name == "s3"

    def test_unknown_mode_falls_back_instead_of_raising(self, monkeypatch) -> None:
        monkeypatch.setenv("STEP1_STORAGE_MODE", "nonsense")
        assert build_object_storage().backend_name == "mock-object-storage"

    def test_presign_expiry_is_clamped(self, monkeypatch) -> None:
        monkeypatch.setenv("S3_PRESIGN_EXPIRY_SECONDS", "999999")
        assert configured_presign_expiry() == 3600
        monkeypatch.setenv("S3_PRESIGN_EXPIRY_SECONDS", "1")
        assert configured_presign_expiry() == 60
        monkeypatch.setenv("S3_PRESIGN_EXPIRY_SECONDS", "not-a-number")
        assert configured_presign_expiry() == 300
