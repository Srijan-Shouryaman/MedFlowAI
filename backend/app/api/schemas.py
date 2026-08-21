"""Request and response models for the document upload API.

These describe storage only.  Extraction, confidence, and review payloads are
deliberately absent: nothing in this service produces them yet, and inventing
placeholder shapes now would make the eventual contract harder to agree on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


InputModality = Literal["typed", "handwritten", "multilingual"]
ProcessingStatus = Literal["complete", "pending_human_verification", "failed"]


class StoredObjectSummary(BaseModel):
    """What the frontend needs to prove the bytes reached the bucket."""

    bucket: str
    key: str
    storage_uri: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    version_id: str | None = None
    backend: str


class UploadDocumentResponse(BaseModel):
    document_id: str
    job_id: str
    processing_status: ProcessingStatus
    # ``stored`` is the addition over the frontend's existing mock contract.
    # It carries no clinical data, so it is safe to render in the UI.
    stored: StoredObjectSummary


class DocumentSourceResponse(BaseModel):
    document_id: str
    download_url: str
    expires_at: datetime
    content_type: str
    size_bytes: int


class DocumentListEntry(BaseModel):
    document_id: str
    patient_id: str
    encounter_id: str
    modality: InputModality
    original_filename: str
    uploaded_at: datetime
    stored: StoredObjectSummary


class DocumentListResponse(BaseModel):
    documents: list[DocumentListEntry] = Field(default_factory=list)


class StorageHealthResponse(BaseModel):
    status: Literal["ok"]
    storage_backend: str
    bucket: str
    persistent: bool


__all__ = [
    "DocumentListEntry",
    "DocumentListResponse",
    "DocumentSourceResponse",
    "InputModality",
    "ProcessingStatus",
    "StorageHealthResponse",
    "StoredObjectSummary",
    "UploadDocumentResponse",
]
