"""Process-local index of uploaded documents.

This is a stand-in for the documents table, not a design choice.  It exists
because the object key is a pure function of ``(patient_id, document_id)`` and
the frontend only ever holds ``document_id``, so something has to remember the
patient a document belongs to.

Everything here is lost on restart.  The objects in MinIO are not -- that is
the distinction this task is meant to demonstrate.  When a database is
introduced, replace this module and keep the same three method names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

from .storage.base import StoredObject


@dataclass(frozen=True)
class DocumentRecord:
    document_id: UUID
    patient_id: str
    encounter_id: str
    modality: str
    source_language: str
    original_filename: str
    stored: StoredObject
    uploaded_at: datetime


class InMemoryDocumentRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[UUID, DocumentRecord] = {}

    def record(
        self,
        *,
        document_id: UUID,
        patient_id: str,
        encounter_id: str,
        modality: str,
        source_language: str,
        original_filename: str,
        stored: StoredObject,
    ) -> DocumentRecord:
        entry = DocumentRecord(
            document_id=document_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            modality=modality,
            source_language=source_language,
            original_filename=original_filename,
            stored=stored,
            uploaded_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._records[document_id] = entry
        return entry

    def get(self, document_id: UUID) -> DocumentRecord | None:
        with self._lock:
            return self._records.get(document_id)

    def list_recent(self, limit: int = 50) -> list[DocumentRecord]:
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda item: item.uploaded_at, reverse=True)
        return records[:limit]


__all__ = ["DocumentRecord", "InMemoryDocumentRegistry"]
