from threading import Lock
from typing import Protocol
from uuid import UUID

from contracts.schemas import ClinicalEventBatch

from .validation import validate_events


class ClinicalEventRepository(Protocol):
    def save(self, batch: ClinicalEventBatch) -> ClinicalEventBatch:
        ...

    def get(self, document_id: UUID) -> ClinicalEventBatch | None:
        ...


class InMemoryClinicalEventRepository:
    def __init__(self) -> None:
        self._batches: dict[UUID, ClinicalEventBatch] = {}
        self._lock = Lock()

    def save(self, batch: ClinicalEventBatch) -> ClinicalEventBatch:
        validate_events(
            batch.clinical_events,
            expected_source_document_id=batch.source_document_id,
        )
        with self._lock:
            self._batches[batch.source_document_id] = batch
        return batch

    def get(self, document_id: UUID) -> ClinicalEventBatch | None:
        with self._lock:
            return self._batches.get(document_id)


class SqlAlchemyClinicalEventRepository:
    """Durable adapter for the shared append-only clinical_events table."""

    def __init__(self, db) -> None:
        self.db = db

    def save(self, batch: ClinicalEventBatch) -> ClinicalEventBatch:
        from database.models import ClinicalEventRecord

        validate_events(
            batch.clinical_events,
            expected_source_document_id=batch.source_document_id,
        )

        try:
            for event in batch.clinical_events:
                existing = (
                    self.db.query(ClinicalEventRecord)
                    .filter(ClinicalEventRecord.id == event.event_local_id)
                    .first()
                )
                if existing is not None:
                    continue
                self.db.add(
                    ClinicalEventRecord(
                        id=event.event_local_id,
                        patient_id=batch.patient_id,
                        encounter_id=batch.encounter_id,
                        source_document_id=batch.source_document_id,
                        event_payload=event.model_dump(mode="json"),
                        validation_status=event.validation_status.value,
                    )
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return batch

    def get(self, document_id: UUID) -> ClinicalEventBatch | None:
        from database.models import ClinicalEventRecord

        records = (
            self.db.query(ClinicalEventRecord)
            .filter(ClinicalEventRecord.source_document_id == document_id)
            .order_by(ClinicalEventRecord.created_at.asc())
            .all()
        )
        if not records:
            return None
        from datetime import datetime, timezone

        events = [record.event_payload for record in records]
        first = records[0]
        return ClinicalEventBatch(
            clinical_events=events,
            patient_id=first.patient_id,
            encounter_id=first.encounter_id,
            source_document_id=document_id,
            processed_at=datetime.now(timezone.utc),
        )
