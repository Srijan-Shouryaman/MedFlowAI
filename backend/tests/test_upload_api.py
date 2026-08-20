"""End-to-end tests for the upload endpoints against in-memory storage."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from app.storage.errors import ObjectStorageRequestError
from conftest import PNG_BYTES


UPLOAD_FORM = {
    "patient_id": "pat_00123",
    "encounter_id": "enc_2026_0817_01",
    "source_language": "en",
}


def _upload(client, *, modality="typed", files=None, form=None):
    return client.post(
        f"/api/v1/step1/documents/{modality}",
        files=files or {"file": ("note.png", PNG_BYTES, "image/png")},
        data={**UPLOAD_FORM, **(form or {})},
    )


class TestUpload:
    def test_uploaded_bytes_reach_storage_unchanged(self, client, storage) -> None:
        response = _upload(client)
        assert response.status_code == 201
        body = response.json()

        key = body["stored"]["key"]
        assert storage.get_content(key=key) == PNG_BYTES
        assert body["stored"]["checksum_sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
        assert body["stored"]["size_bytes"] == len(PNG_BYTES)
        assert body["stored"]["content_type"] == "image/png"

    def test_key_contains_the_patient_and_document_but_not_the_filename(
        self, client
    ) -> None:
        body = _upload(
            client, files={"file": ("Ananya_Mehta_rx.png", PNG_BYTES, "image/png")}
        ).json()
        key = body["stored"]["key"]
        assert key == (
            f"step1/patients/pat_00123/documents/{body['document_id']}/source"
        )
        assert "Ananya" not in key

    @pytest.mark.parametrize("modality", ["typed", "handwritten", "multilingual"])
    def test_every_modality_persists(self, client, storage, modality) -> None:
        body = _upload(client, modality=modality).json()
        assert storage.head(key=body["stored"]["key"]).size_bytes == len(PNG_BYTES)

    def test_each_upload_gets_its_own_key(self, client, storage) -> None:
        first = _upload(client).json()["stored"]["key"]
        second = _upload(client).json()["stored"]["key"]
        assert first != second
        assert storage.get_content(key=first) == storage.get_content(key=second)


class TestUploadValidation:
    def test_mismatched_content_is_rejected(self, client) -> None:
        # A PDF renamed to .png with an image/png content type.  The extension
        # and declared type agree with each other and lie about the bytes.
        response = _upload(
            client, files={"file": ("fake.png", b"%PDF-1.7\n%%EOF\n", "image/png")}
        )
        assert response.status_code == 415

    def test_disallowed_type_is_rejected(self, client) -> None:
        response = _upload(
            client,
            files={"file": ("run.exe", b"MZ\x90\x00", "application/x-msdownload")},
        )
        assert response.status_code == 415

    def test_path_traversal_in_filename_is_rejected(self, client) -> None:
        response = _upload(
            client, files={"file": ("../../etc/passwd.png", PNG_BYTES, "image/png")}
        )
        assert response.status_code == 400

    def test_path_traversal_in_patient_id_is_rejected(self, client) -> None:
        response = _upload(client, form={"patient_id": "../../../etc"})
        assert response.status_code == 400

    def test_empty_file_is_rejected(self, client) -> None:
        response = _upload(client, files={"file": ("empty.png", b"", "image/png")})
        assert response.status_code == 400

    def test_oversized_file_is_rejected(self, client, monkeypatch) -> None:
        monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "16")
        response = _upload(client)
        assert response.status_code == 413

    def test_nothing_is_stored_when_validation_fails(self, client, storage) -> None:
        _upload(client, files={"file": ("run.exe", b"MZ", "application/x-msdownload")})
        assert client.get("/api/v1/step1/documents").json()["documents"] == []


class TestStorageFailure:
    def test_storage_failure_is_503_not_a_successful_upload(self, client) -> None:
        # The upload must not come back 2xx with a "failed" status: the caller
        # would reasonably read that as "we have your file, processing broke".
        def explode(**_kwargs):
            raise ObjectStorageRequestError("down")

        client.app.state.object_storage.put = explode
        response = _upload(client)
        assert response.status_code == 503
        assert "not saved" in response.json()["detail"]


class TestRetrieval:
    def test_source_url_round_trips_the_uploaded_document(self, client) -> None:
        document_id = _upload(client).json()["document_id"]
        response = client.get(f"/api/v1/step1/documents/{document_id}/source")
        assert response.status_code == 200
        body = response.json()
        assert body["content_type"] == "image/png"
        assert body["size_bytes"] == len(PNG_BYTES)
        assert body["download_url"].startswith("memory://")

    def test_unknown_document_is_404(self, client) -> None:
        response = client.get(f"/api/v1/step1/documents/{uuid4()}/source")
        assert response.status_code == 404

    def test_malformed_document_id_is_422(self, client) -> None:
        assert client.get("/api/v1/step1/documents/not-a-uuid/source").status_code == 422

    def test_listing_reports_what_was_uploaded(self, client) -> None:
        _upload(client, files={"file": ("a.png", PNG_BYTES, "image/png")})
        _upload(client, modality="handwritten")
        documents = client.get("/api/v1/step1/documents").json()["documents"]
        assert len(documents) == 2
        assert {item["modality"] for item in documents} == {"typed", "handwritten"}


class TestHealth:
    def test_health_reports_whether_storage_is_persistent(self, client) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        # The fixture swaps in mock storage, so this must report non-persistent.
        assert body["persistent"] is False
        assert body["storage_backend"] == "mock-object-storage"
