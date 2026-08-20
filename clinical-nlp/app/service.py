from datetime import datetime, timezone
from uuid import UUID

from contracts.schemas import ClinicalEventBatch, ProcessingStatus, Step1Output

from .adapters import NLPAdapterBundle, build_adapter_bundle
from .pipeline import ClinicalNLPPipeline
from .repository import ClinicalEventRepository, InMemoryClinicalEventRepository
from .validation import ClinicalEventValidationError


class Step1InputError(ValueError):
    pass


class ClinicalNLPProcessingError(RuntimeError):
    pass


class ClinicalEventBatchNotFoundError(LookupError):
    pass


class ClinicalNLPService:
    def __init__(
        self,
        *,
        pipeline: ClinicalNLPPipeline | None = None,
        adapters: NLPAdapterBundle | None = None,
        repository: ClinicalEventRepository | None = None,
    ) -> None:
        self.pipeline = pipeline or ClinicalNLPPipeline(adapters=adapters or build_adapter_bundle())
        self.repository = repository or InMemoryClinicalEventRepository()

    def process(
        self,
        *,
        document_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        step1_output: Step1Output,
    ) -> ClinicalEventBatch:
        self._validate_step1_input(
            document_id=document_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            step1_output=step1_output,
        )

        try:
            events = self.pipeline.process(step1_output)
        except ClinicalEventValidationError as exc:
            raise Step1InputError(str(exc)) from exc
        except Exception as exc:
            raise ClinicalNLPProcessingError(str(exc)) from exc

        batch = ClinicalEventBatch(
            clinical_events=events,
            patient_id=patient_id,
            encounter_id=encounter_id,
            source_document_id=document_id,
            processed_at=datetime.now(timezone.utc),
        )
        return self.repository.save(batch)

    def get(self, document_id: UUID) -> ClinicalEventBatch:
        batch = self.repository.get(document_id)
        if batch is None:
            raise ClinicalEventBatchNotFoundError(str(document_id))
        return batch

    @staticmethod
    def _validate_step1_input(
        *,
        document_id: UUID,
        patient_id: UUID,
        encounter_id: UUID,
        step1_output: Step1Output,
    ) -> None:
        if step1_output.document_id != document_id:
            raise Step1InputError("document_id does not match Step1Output.")
        if step1_output.patient_id != patient_id:
            raise Step1InputError("patient_id does not match Step1Output.")
        if step1_output.encounter_id != encounter_id:
            raise Step1InputError("encounter_id does not match Step1Output.")
        if step1_output.processing_status != ProcessingStatus.COMPLETE:
            raise Step1InputError(
                "Only complete Step1Output may enter Clinical NLP."
            )
        if any(
            field.requires_doctor_review_before_memory_write
            for field in step1_output.extracted_fields
        ):
            raise Step1InputError(
                "Step1Output contains fields awaiting physician verification."
            )
