from uuid import UUID, uuid4

from contracts.schemas import ClinicalEvent, ClinicalEventValidationStatus, SourceTextSpan

from ..contextualization import ContextualizationResult
from ..ner import EntitySpan
from ..terminology import TerminologyMatch
from ..abbreviations import ExpandedField


def _source_span(field: ExpandedField, entity: EntitySpan, match: TerminologyMatch) -> SourceTextSpan:
    original = field.source.original_text
    lowered = original.casefold()
    for candidate in (entity.text, match.matched_text):
        start = lowered.find(candidate.casefold())
        if start >= 0:
            return SourceTextSpan(start=start, end=start + len(candidate))
    return field.source.source_text_span


def build_clinical_event(
    *,
    field: ExpandedField,
    terminology: TerminologyMatch,
    entity: EntitySpan,
    context: ContextualizationResult,
    source_document_id: UUID,
    input_modality,
    source_language: str,
    translation_confidence: float,
) -> ClinicalEvent:
    return ClinicalEvent(
        event_local_id=uuid4(),
        original_text=field.source.original_text,
        processed_text=field.processed_text,
        normalized_concept=terminology.concept,
        snomed_ct_id=terminology.snomed_ct_id,
        entity_type=entity.entity_type,
        clinical_domain=terminology.clinical_domain,
        relationships=[],
        assertion=context.assertion,
        clinical_status=context.clinical_status,
        temporal_context=context.temporal_context,
        temporal_date=context.temporal_date,
        bioclinicalbert_confidence=entity.confidence,
        gemini_contextualization_confidence=context.confidence,
        source_document_id=source_document_id,
        source_text_span=_source_span(field, entity, terminology),
        input_modality=input_modality,
        source_language=source_language,
        translation_confidence=translation_confidence,
        validation_status=ClinicalEventValidationStatus.VALID,
    )
