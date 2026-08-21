"""Document upload and retrieval.

Scope note: this router persists the original uploaded bytes and hands back a
short-lived URL to read them again.  It performs no OCR, no extraction, and no
clinical processing -- those belong to services that do not exist yet.  The
``processing_status`` it returns describes storage, nothing more.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..registry import InMemoryDocumentRegistry
from ..storage.base import ObjectStorage, StoredObject
from ..storage.errors import ObjectStorageError, ObjectStorageNotFoundError
from ..storage.factory import configured_presign_expiry
from ..storage.keys import UnsafeIdentifierError, build_source_key, download_filename
from ..upload_security import UploadSecurityError, read_validated_upload
from .dependencies import get_document_registry, get_object_storage
from .schemas import (
    DocumentListEntry,
    DocumentListResponse,
    DocumentSourceResponse,
    InputModality,
    StoredObjectSummary,
    UploadDocumentResponse,
)


logger = logging.getLogger("medflow.documents")

router = APIRouter(prefix="/api/v1/step1/documents", tags=["step1-documents"])


def _summarize(stored: StoredObject, backend: str) -> StoredObjectSummary:
    return StoredObjectSummary(
        bucket=stored.bucket,
        key=stored.key,
        storage_uri=stored.storage_uri,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        version_id=stored.version_id,
        backend=backend,
    )


async def _store_upload(
    *,
    modality: InputModality,
    file: UploadFile,
    patient_id: str,
    encounter_id: str,
    source_language: str,
    storage: ObjectStorage,
    registry: InMemoryDocumentRegistry,
) -> UploadDocumentResponse:
    try:
        upload = await read_validated_upload(file)
    except UploadSecurityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    document_id = uuid4()
    try:
        key = build_source_key(patient_id=patient_id, document_id=document_id)
    except UnsafeIdentifierError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        stored = storage.put(
            key=key,
            content=upload.content,
            content_type=upload.content_type,
        )
    except ObjectStorageError as exc:
        # A storage failure means the document was never persisted.  Returning
        # a "failed" processing status here would imply the upload was accepted
        # and then went wrong later, which is not what happened.
        logger.error(
            "Failed to persist uploaded document",
            extra={"backend": storage.backend_name, "modality": modality},
        )
        raise HTTPException(
            status_code=503,
            detail="Document storage is unavailable. The upload was not saved.",
        ) from exc

    registry.record(
        document_id=document_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        modality=modality,
        source_language=source_language,
        original_filename=upload.filename,
        stored=stored,
    )
    logger.info(
        "Stored uploaded document",
        extra={
            "backend": storage.backend_name,
            "bucket": stored.bucket,
            "modality": modality,
            "size_bytes": stored.size_bytes,
        },
    )

    return UploadDocumentResponse(
        document_id=str(document_id),
        job_id=f"job_{document_id.hex[:12]}",
        # Storage succeeded and nothing has been extracted, so every document
        # is waiting on a human until an extraction service exists.
        processing_status="pending_human_verification",
        stored=_summarize(stored, storage.backend_name),
    )


@router.post("/typed", response_model=UploadDocumentResponse, status_code=201)
async def upload_typed_document(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    encounter_id: str = Form(...),
    source_language: str = Form("en"),
    storage: ObjectStorage = Depends(get_object_storage),
    registry: InMemoryDocumentRegistry = Depends(get_document_registry),
) -> UploadDocumentResponse:
    return await _store_upload(
        modality="typed",
        file=file,
        patient_id=patient_id,
        encounter_id=encounter_id,
        source_language=source_language,
        storage=storage,
        registry=registry,
    )


@router.post("/handwritten", response_model=UploadDocumentResponse, status_code=201)
async def upload_handwritten_document(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    encounter_id: str = Form(...),
    source_language: str = Form("en"),
    storage: ObjectStorage = Depends(get_object_storage),
    registry: InMemoryDocumentRegistry = Depends(get_document_registry),
) -> UploadDocumentResponse:
    return await _store_upload(
        modality="handwritten",
        file=file,
        patient_id=patient_id,
        encounter_id=encounter_id,
        source_language=source_language,
        storage=storage,
        registry=registry,
    )


@router.post("/multilingual", response_model=UploadDocumentResponse, status_code=201)
async def upload_multilingual_document(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    encounter_id: str = Form(...),
    source_language: str = Form("hi"),
    storage: ObjectStorage = Depends(get_object_storage),
    registry: InMemoryDocumentRegistry = Depends(get_document_registry),
) -> UploadDocumentResponse:
    return await _store_upload(
        modality="multilingual",
        file=file,
        patient_id=patient_id,
        encounter_id=encounter_id,
        source_language=source_language,
        storage=storage,
        registry=registry,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    registry: InMemoryDocumentRegistry = Depends(get_document_registry),
    storage: ObjectStorage = Depends(get_object_storage),
) -> DocumentListResponse:
    """Documents uploaded since this process started.

    Backed by the in-memory registry, so it is a view of this process, not of
    the bucket.  To inspect the bucket itself, use the MinIO console or
    ``scripts/verify_minio_upload.sh``.
    """

    return DocumentListResponse(
        documents=[
            DocumentListEntry(
                document_id=str(record.document_id),
                patient_id=record.patient_id,
                encounter_id=record.encounter_id,
                modality=record.modality,
                original_filename=record.original_filename,
                uploaded_at=record.uploaded_at,
                stored=_summarize(record.stored, storage.backend_name),
            )
            for record in registry.list_recent()
        ]
    )


@router.get("/{document_id}/source", response_model=DocumentSourceResponse)
def get_document_source(
    document_id: UUID,
    registry: InMemoryDocumentRegistry = Depends(get_document_registry),
    storage: ObjectStorage = Depends(get_object_storage),
) -> DocumentSourceResponse:
    """Presigned URL for the original bytes.

    The URL carries its own signature and is not protected by this service.
    Anyone holding it can read the document until it expires, so the expiry is
    kept short and the URL is never logged.
    """

    record = registry.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    expires_in = configured_presign_expiry()
    try:
        presigned = storage.presign_get(
            key=record.stored.key,
            expires_in=expires_in,
            download_filename=download_filename(
                document_id, record.stored.content_type
            ),
        )
    except ObjectStorageNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="No stored source document.",
        ) from exc
    except ObjectStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Document storage is unavailable.",
        ) from exc

    return DocumentSourceResponse(
        document_id=str(document_id),
        download_url=presigned.url,
        expires_at=presigned.expires_at,
        content_type=presigned.content_type,
        size_bytes=presigned.size_bytes,
    )


__all__ = ["router"]
